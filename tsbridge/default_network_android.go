//go:build android

package tsbridge

import "tailscale.com/net/netmon"

func updateDefaultNetwork(defaultInterface, defaultGateway string) {
	netmon.UpdateLastKnownDefaultRouteInterface(defaultInterface)
	netmon.UpdateLastKnownDefaultGateway(defaultGateway)
}
