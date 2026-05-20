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

Current local app port used by `start_app.bat` and `start_shopping_app.py`:

```text
5080
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

If Pythonista prints:

```text
SSHClient.connect() got an unexpected keyword argument 'auth_timeout'
```

the phone has an older Paramiko version. Update Paramiko in Pythonista if possible, or edit `start_shopping_app.py` on the phone and remove the `auth_timeout=SSH_TIMEOUT` and `banner_timeout=SSH_TIMEOUT` lines from `ssh_client.connect(...)`.

If the app opens but you no longer want it public, turn Funnel off:

```powershell
tailscale funnel --https=443 off
```

## Detailed Setup And Checks

Follow these steps from top to bottom when setting up or debugging the phone launcher.

### 1. Confirm Flask Is Running Locally

Run this on the Windows PC from PowerShell:

```powershell
curl.exe -sS --noproxy "*" --max-time 8 http://127.0.0.1:5080/ -o NUL -w "%{http_code}`n"
```

Expected output:

```text
200
```

Next step:

- If you get `200`, Flask is running.
- If you get `000` or a connection error, start the app:

```powershell
py -3.11 app.py
```

or:

```powershell
.\start_app.bat
```

### 2. Confirm Flask Is Reachable On The LAN

Run this on the Windows PC:

```powershell
curl.exe -sS --noproxy "*" --max-time 8 http://192.168.68.62:5080/ -o NUL -w "%{http_code}`n"
```

Expected output:

```text
200
```

Next step:

- If this works, Flask is listening on the network.
- If local `127.0.0.1` works but LAN does not, check Windows Firewall and confirm the PC's LAN IP has not changed.

### 3. Confirm Tailscale Sees The Phone

Run this on the Windows PC:

```powershell
tailscale status
```

Expected output includes both devices:

```text
100.112.145.109  desktop-in7s09s    ... windows
100.121.121.80   iphone-15-pro-max  ... iOS
```

Next step:

- If the iPhone says `offline`, open Tailscale on the iPhone and connect it.
- If the iPhone is missing entirely, sign into the same Tailscale account on the phone.

### 4. Confirm Windows SSH Is Running

Run this on the Windows PC:

```powershell
Get-Service sshd
```

Expected output:

```text
Status   Name
------   ----
Running  sshd
```

Next step:

- If it is not running, start it:

```powershell
Start-Service sshd
```

- To make it start automatically:

```powershell
Set-Service -Name sshd -StartupType Automatic
```

### 5. Confirm Port 22 Is Listening

Run this on the Windows PC:

```powershell
netstat -ano | findstr ":22"
```

Expected output includes:

```text
TCP    0.0.0.0:22    0.0.0.0:0    LISTENING
TCP    [::]:22       [::]:0       LISTENING
```

Next step:

- If port `22` is listening, Pythonista should be able to SSH when Tailscale is connected.
- If not, restart OpenSSH Server:

```powershell
Restart-Service sshd
```

### 6. Turn On Public Funnel

Run this on the Windows PC:

```powershell
tailscale funnel --bg --yes http://127.0.0.1:5080
```

Expected output:

```text
Available on the internet:

https://desktop-in7s09s.tail906b20.ts.net/
|-- proxy http://127.0.0.1:5080

Funnel started and running in the background.
```

Next step:

- If this succeeds, the public URL should work.
- If it fails, check that Funnel is enabled for the tailnet in the Tailscale admin console.

### 7. Confirm Funnel Status

Run this on the Windows PC:

```powershell
tailscale funnel status
```

Expected output:

```text
# Funnel on:
#     - https://desktop-in7s09s.tail906b20.ts.net

https://desktop-in7s09s.tail906b20.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:5080
```

Next step:

- If Funnel is on, open the app URL from Safari:

```text
https://desktop-in7s09s.tail906b20.ts.net/
```

### 8. Test The Phone Script

In Pythonista, run:

```text
start_shopping_app.py
```

Expected output if the app is already online:

```text
Shopping app is already online
Opening Safari: https://desktop-in7s09s.tail906b20.ts.net/
SSH closed
```

Expected output if the script needs to start the app:

```text
Running Shortcut: Connect Tailscale
Make sure Tailscale says Connected, then return to Pythonista.
Press Enter here after Tailscale is connected...
Connecting to Windows PC over Tailscale...
Trying SSH host: 100.112.145.109
SSH connected: 100.112.145.109
Launching Flask app...
Ensuring Tailscale Funnel is on...
Waiting for shopping app...
Shopping app is online
Opening Safari: https://desktop-in7s09s.tail906b20.ts.net/
SSH closed
```

Next step:

- If it opens Safari, the setup is working.
- If it times out during SSH, Tailscale or Windows SSH is still not reachable from the phone.
- If SSH works but Safari does not open, update `open_in_safari` in the script to use `openURL_options_completionHandler_`.

### 9. Turn Off Public Access When Done

Run this on the Windows PC:

```powershell
tailscale funnel --https=443 off
```

Expected output:

```text
```

No output is normal.

Next step:

- Confirm Funnel is off:

```powershell
tailscale funnel status
```
