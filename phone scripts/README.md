# Phone Scripts

Scripts in this folder are meant to be copied into Pythonista on the iPhone.

## start_shopping_app.py

Starts the shopping-list Flask app on the Windows PC over Tailscale SSH, ensures Tailscale Funnel is enabled, waits for the public HTTPS URL to respond, then opens Safari.

If the public Funnel URL is already online, the script skips SSH and opens Safari immediately.

Before running it, create an iOS Shortcut named:

```text
Connect Tailscale
```

Add Tailscale's built-in **Connect** action to that Shortcut. The script runs this Shortcut first, then asks you to return to Pythonista and press Enter once Tailscale says connected.

The script tries SSH in this order:

```text
100.112.145.109
desktop-in7s09s.tail906b20.ts.net
desktop-in7s09s
```

The raw Tailscale IP is first because Pythonista/iPhone DNS can be less reliable than connecting directly to the Tailscale address.

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

## Troubleshooting

If Pythonista prints:

```text
EXCEPTION: timed out
```

while connecting over SSH, the phone cannot reach Windows SSH yet. Check these first:

- Tailscale on the iPhone says **Connected**.
- The Windows PC is online in Tailscale.
- Windows OpenSSH Server is running.
- Port `22` is listening on the Windows PC.

Useful PowerShell checks on the PC:

```powershell
tailscale status
Get-Service sshd
netstat -ano | findstr ":22"
```

If the app opens but you no longer want it public, turn Funnel off:

```powershell
tailscale funnel --https=443 off
```
