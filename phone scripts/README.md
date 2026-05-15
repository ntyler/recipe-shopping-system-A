# Phone Scripts

Scripts in this folder are meant to be copied into Pythonista on the iPhone.

## start_shopping_app.py

Starts the shopping-list Flask app on the Windows PC over Tailscale SSH, ensures Tailscale Funnel is enabled, waits for the public HTTPS URL to respond, then opens Safari.

Before running it, create an iOS Shortcut named:

```text
Connect Tailscale
```

Add Tailscale's built-in **Connect** action to that Shortcut. The script runs this Shortcut first, then asks you to return to Pythonista and press Enter once Tailscale says connected.

Expected Pythonista packages/imports:

- `paramiko`
- `requests`
- `keychain`
- `objc_util`

The script expects the Windows SSH password to be saved in Pythonista's keychain:

```python
keychain.set_password("windows_ssh", "Tyler", "your_windows_password")
```

Current app URL:

```text
https://desktop-in7s09s.tail906b20.ts.net/
```

Turn off public access from PowerShell when you are done:

```powershell
tailscale funnel --https=443 off
```
