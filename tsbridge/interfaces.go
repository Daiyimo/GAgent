// Android SDK 30+ 禁止普通应用用 netlink(NETLINK_ROUTE bind / RTM_GETLINK),
// Go 标准库 net.Interfaces() 在真机上直接 "netlinkrib: permission denied"(模拟器
// SELinux permissive 才侥幸通过)。官方 tailscale-android 的解法: Java 侧用系统放行的
// NetworkInterface API 枚举网卡, 序列化成 JSON 交给 Go, 经 netmon.RegisterInterfaceGetter
// 替换掉 net.Interfaces()。本文件即该方案的 tsbridge 版(schema 与官方 libtailscale 对齐)。
//
// Kotlin 侧须在 Up() 之前调 SetInterfacesJSON(json); 网络切换后重复调用可刷新快照。
package tsbridge

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"sync"

	"tailscale.com/net/netmon"
)

var (
	ifsMu  sync.Mutex
	altIfs []netmon.Interface // Java 侧注入的网卡快照(替代 net.Interfaces())
)

type addrJSON struct {
	IP        string `json:"ip"`
	PrefixLen int    `json:"prefixLen"`
}

type ifaceJSON struct {
	Name      string     `json:"name"`
	Index     int        `json:"index"`
	MTU       int        `json:"mtu"`
	Up        bool       `json:"up"`
	Broadcast bool       `json:"broadcast"`
	Loopback  bool       `json:"loopback"`
	PointToPt bool       `json:"pointToPoint"`
	Multicast bool       `json:"multicast"`
	Addrs     []addrJSON `json:"addrs"`
}

func init() {
	// 注册一次, 永远生效: tsnet 内部所有 netInterfaces() 调用都改走注入的快照。
	netmon.RegisterInterfaceGetter(func() ([]netmon.Interface, error) {
		ifsMu.Lock()
		defer ifsMu.Unlock()
		if len(altIfs) == 0 {
			return nil, errors.New("tsbridge: interfaces not injected (call SetInterfacesJSON first)")
		}
		out := make([]netmon.Interface, len(altIfs))
		copy(out, altIfs)
		return out, nil
	})
}

// SetInterfacesJSON 接收 Java 侧枚举的网卡列表(JSON 数组), 解析后作为
// net.Interfaces() 的替代品供 tsnet 使用。gomobile 导出: Tsbridge.setInterfacesJSON。
func SetInterfacesJSON(s string) error {
	var in []ifaceJSON
	if err := json.Unmarshal([]byte(s), &in); err != nil {
		return fmt.Errorf("tsbridge: bad interfaces json: %w", err)
	}
	out := make([]netmon.Interface, 0, len(in))
	for _, it := range in {
		if it.Name == "" {
			continue
		}
		nif := netmon.Interface{
			Interface: &net.Interface{
				Name:  it.Name,
				Index: it.Index,
				MTU:   it.MTU,
			},
			AltAddrs: []net.Addr{},
		}
		if it.Up {
			nif.Flags |= net.FlagUp
		}
		if it.Broadcast {
			nif.Flags |= net.FlagBroadcast
		}
		if it.Loopback {
			nif.Flags |= net.FlagLoopback
		}
		if it.PointToPt {
			nif.Flags |= net.FlagPointToPoint
		}
		if it.Multicast {
			nif.Flags |= net.FlagMulticast
		}
		for _, a := range it.Addrs {
			if na, err := a.netAddr(); err == nil {
				nif.AltAddrs = append(nif.AltAddrs, na)
			}
		}
		out = append(out, nif)
	}
	ifsMu.Lock()
	altIfs = out
	ifsMu.Unlock()
	return nil
}

func (a addrJSON) netAddr() (net.Addr, error) {
	na, err := netip.ParseAddr(a.IP)
	if err != nil {
		return nil, err
	}
	ip := net.IP(na.AsSlice())
	if zone := na.Zone(); zone != "" {
		return &net.IPAddr{IP: ip, Zone: zone}, nil // 带 zone 的地址表示不成 *net.IPNet
	}
	bits := 128
	if na.Is4() {
		bits = 32
	}
	if a.PrefixLen < 0 || a.PrefixLen > bits {
		return &net.IPAddr{IP: ip}, nil
	}
	return &net.IPNet{IP: ip, Mask: net.CIDRMask(a.PrefixLen, bits)}, nil
}
