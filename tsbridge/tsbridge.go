// Package tsbridge 把 tsnet(用户态 tailscale) 封装成 gomobile 可绑定的极简 API。
// GA 门控入网: app 登录 GAuth 拿 JWT → provision 换 preauthkey → Up() 入网 →
// Forward() 把 127.0.0.1:<port> 转发到 tailnet 里的 PC(如 100.64.0.1:48222)，
// 手机侧 Python 直接 ssh localhost:<port> 即可到达电脑。
//
// gomobile 约束: 导出函数只用基本类型(string/int/error)。所有状态是包级单例
// (一台手机同时只需要一个 tailscale 节点)。
package tsbridge

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"tailscale.com/tsnet"
)

var (
	mu                 sync.Mutex
	srv                *tsnet.Server
	forwardListener    net.Listener
	selfIP             string
	currentRemoteAddr  string
	currentForwardPort int
)

// Up 启动嵌入式 tailscale 节点并阻塞到连上控制面(或报错)。
// dataDir: app 可写目录(状态/密钥落这里, 如 ctx.filesDir/tsnet);
// controlURL: headscale 控制面(https://headscale.152-53-241-20.sslip.io);
// authKey: provision 铸出的持久节点 single-use preauthkey;
// hostname: 节点名(如 ga-phone-<uid>)。
func Up(dataDir, controlURL, authKey, hostname string) error {
	mu.Lock()
	defer mu.Unlock()
	if srv != nil {
		return fmt.Errorf("tsbridge: already up (call Down first)")
	}
	// Android 无 $HOME/$XDG_*，tsnet 内部 os.UserConfigDir()/日志状态目录会解析失败并
	// panic("no safe place found to store log state")。把这些指向 app 可写目录即可。
	if err := os.MkdirAll(dataDir, 0700); err != nil {
		return fmt.Errorf("tsbridge mkdir: %w", err)
	}
	logsDir := filepath.Join(dataDir, "logs")
	_ = os.MkdirAll(logsDir, 0700)
	os.Setenv("HOME", dataDir)
	os.Setenv("XDG_CONFIG_HOME", dataDir)
	os.Setenv("XDG_CACHE_HOME", dataDir)
	os.Setenv("XDG_STATE_HOME", dataDir)
	os.Setenv("TMPDIR", dataDir)
	os.Setenv("TS_LOGS_DIR", logsDir)
	// tsnet otherwise collapses a deleted server-side node and a transient control
	// plane outage into context deadline exceeded. Record only its public auth-required
	// diagnostic so callers can re-enroll the former without treating every timeout as
	// permission to discard state.
	var authRequired atomic.Bool
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	s := &tsnet.Server{
		Dir:        dataDir,
		ControlURL: controlURL,
		AuthKey:    authKey,
		Hostname:   hostname,
		Ephemeral:  false,
		UserLogf: func(format string, args ...any) {
			line := fmt.Sprintf(format, args...)
			if strings.Contains(line, "restart with TS_AUTHKEY set") {
				authRequired.Store(true)
				cancel()
			}
		},
		Logf: func(string, ...any) {}, // suppress verbose backend logs; auth state is UserLogf

	}
	st, err := s.Up(ctx)
	if err != nil {
		s.Close()
		if authKey == "" && authRequired.Load() {
			return errors.New("tsbridge_auth_required")
		}
		return fmt.Errorf("tsbridge up: %w", err)
	}
	srv = s
	selfIP = ""
	if st != nil && len(st.TailscaleIPs) > 0 {
		selfIP = st.TailscaleIPs[0].String()
	}
	return nil
}

// StatusJSON 返回实际运行节点与当前单一转发目标。
func StatusJSON() string {
	mu.Lock()
	defer mu.Unlock()
	m := map[string]any{
		"running":     srv != nil,
		"ip":          selfIP,
		"forwards":    boolToInt(forwardListener != nil),
		"remoteAddr":  currentRemoteAddr,
		"forwardPort": currentForwardPort,
	}
	b, _ := json.Marshal(m)
	return string(b)
}

// Forward 在 127.0.0.1:localPort 起监听, 每个连接经 tailnet 拨到 remoteAddr。
// 相同端口切换电脑时只更新目标，已有连接继续使用旧目标，新连接使用新目标。
func Forward(localPort int, remoteAddr string) error {
	mu.Lock()
	if srv == nil {
		mu.Unlock()
		return fmt.Errorf("tsbridge: not up")
	}
	if forwardListener != nil && currentForwardPort == localPort {
		currentRemoteAddr = remoteAddr
		mu.Unlock()
		return nil
	}
	old := forwardListener
	forwardListener = nil
	currentForwardPort = 0
	currentRemoteAddr = ""
	mu.Unlock()
	if old != nil {
		old.Close()
	}
	ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", localPort))
	if err != nil {
		return fmt.Errorf("tsbridge listen: %w", err)
	}
	mu.Lock()
	if srv == nil {
		mu.Unlock()
		ln.Close()
		return fmt.Errorf("tsbridge: not up")
	}
	forwardListener = ln
	currentForwardPort = localPort
	currentRemoteAddr = remoteAddr
	mu.Unlock()
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			mu.Lock()
			s, target := srv, currentRemoteAddr
			active := forwardListener == ln
			mu.Unlock()
			if !active || s == nil || target == "" {
				c.Close()
				continue
			}
			go proxy(s, c, target)
		}
	}()
	return nil
}

func boolToInt(value bool) int {
	if value {
		return 1
	}
	return 0
}

func proxy(s *tsnet.Server, c net.Conn, remoteAddr string) {
	defer c.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	rc, err := s.Dial(ctx, "tcp", remoteAddr)
	cancel()
	if err != nil {
		return
	}
	defer rc.Close()
	done := make(chan struct{}, 2)
	go func() { io.Copy(rc, c); done <- struct{}{} }()
	go func() { io.Copy(c, rc); done <- struct{}{} }()
	<-done // 任一方向断开即收尾
}

// DialTest 经 tsnet 拨一次 remoteAddr, 立即关掉; 返回 "" 表示成功, 否则返回错误串。
// 排障用: 区分「转发器问题」和「tailnet 到目标不通」。
func DialTest(remoteAddr string) string {
	mu.Lock()
	s := srv
	mu.Unlock()
	if s == nil {
		return "not up"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	c, err := s.Dial(ctx, "tcp", remoteAddr)
	if err != nil {
		return err.Error()
	}
	c.Close()
	return ""
}

// Down 关掉所有转发与节点(幂等)。
func Down() {
	mu.Lock()
	defer mu.Unlock()
	if forwardListener != nil {
		forwardListener.Close()
		forwardListener = nil
	}
	if srv != nil {
		srv.Close()
		srv = nil
	}
	selfIP = ""
	currentRemoteAddr = ""
	currentForwardPort = 0
}
