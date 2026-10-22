package tsbridge

// NetworkChanged publishes one coherent Android network snapshot and wakes the
// monitor owned by the running tsnet server. The Sys API is unstable, but it is
// the only type-safe route to that exact monitor in the pinned Tailscale v1.100.0;
// using a second Monitor would not rebind this server's engine.
func NetworkChanged(interfacesJSON, defaultInterface, defaultGateway string) error {
	if err := SetInterfacesJSON(interfacesJSON); err != nil {
		return err
	}
	updateDefaultNetwork(defaultInterface, defaultGateway)

	mu.Lock()
	defer mu.Unlock()
	if srv == nil {
		return nil
	}
	if monitor, ok := srv.Sys().NetMon.GetOK(); ok && monitor != nil {
		monitor.InjectEvent()
	}
	return nil
}
