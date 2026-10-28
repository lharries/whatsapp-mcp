# GitHub Codespaces: link WhatsApp and export your history

This guide is for the account owner to initiate the QR login. **Do not share the QR image or session files.**

## 1. Open a Codespace on the setup branch

1. Open https://github.com/sachin7x/whatsapp-mcp/tree/feat/private-history-export
2. Choose **Code → Codespaces → Create codespace on feat/private-history-export**. If GitHub does not offer this option, open the repository's **Code → Codespaces** tab and create a Codespace from that branch.
3. Wait for the environment to finish building. Keep this Codespace private to your GitHub account.

## 2. Start the bridge and display the QR

In the Codespaces terminal:

```bash
cd whatsapp-bridge
go run main.go
```

The bridge should print a QR code in the terminal on first login. If it is rendered as terminal text, scan it from another screen/device. Do not paste the QR into an issue, chat, email, screenshot, or commit.

On the iPhone running the WhatsApp Business account:
**WhatsApp Business → Settings → Linked Devices → Link a Device**, authenticate with Face ID/passcode if asked, then scan the QR shown by the bridge.

Only the account owner should perform this step. If WhatsApp Business is not the account you intend to archive, stop before scanning.

## 3. Wait for sync

Leave the bridge running and watch its terminal output. History sync time depends on account size and what WhatsApp makes available to the linked device. Codespaces can stop after inactivity; stopping the bridge can interrupt syncing. Do not assume the archive is complete until counts and date ranges have been checked.

## 4. Export the local database

Open a **second terminal** in the same Codespace, then run:

```bash
cd /workspaces/whatsapp-mcp
python3 tools/export_history.py
```

If your workspace folder has a different name, run the script from the repository root instead. The exporter expects `whatsapp-bridge/store/messages.db` to exist.

The result goes into a timestamped `private-export/` folder. It is ignored by Git. Download the files only to a private device/storage location and do not commit them.

## Security and reliability notes

- A GitHub repository is for code, not a private WhatsApp archive. Do not upload `messages.db`, `whatsapp.db`, media, session credentials or QR codes to the repo.
- This project uses an unofficial WhatsApp Web multi-device protocol, not an official WhatsApp history-export API. It may disconnect, need reauthentication, or be affected by WhatsApp changes.
- Codespaces is a development environment, not a guaranteed always-on service. For a large archive, use a persistent private machine with encrypted storage and backups if Codespaces stops before sync finishes.
- The export script is read-only. It exports records already stored locally and cannot recover messages that never synced.
