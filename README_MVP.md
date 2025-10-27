# WhatsApp Cloud Sync - MVP

A minimal proof-of-concept tool to backup WhatsApp images to AWS S3.

## Features (MVP)

- Monitor ONE WhatsApp group
- Download and backup image files only
- Upload to AWS S3
- Manual WhatsApp Web authentication
- Simple console output

## Prerequisites

- Python 3.8+
- AWS Account with S3 bucket
- WhatsApp account

## Quick Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure AWS S3

Edit `config.json`:

```json
{
  "whatsapp": {
    "group_name": "Your Group Name Here"
  },
  "aws": {
    "bucket_name": "your-s3-bucket-name",
    "region": "us-east-1",
    "access_key_id": "YOUR_AWS_ACCESS_KEY",
    "secret_access_key": "YOUR_AWS_SECRET_KEY"
  }
}
```

**AWS Setup:**
1. Create an S3 bucket in your AWS account
2. Create an IAM user with S3 write permissions
3. Generate access keys for the IAM user
4. Add the credentials to `config.json`

### 3. Run the Script

```bash
python simple_monitor.py
```

### 4. Authenticate

1. Browser will open with WhatsApp Web
2. Scan the QR code with your phone
3. Script will automatically find your group and download images
4. Images will be uploaded to S3

## How It Works

1. Opens WhatsApp Web in a browser (Playwright)
2. Waits for you to scan QR code
3. Searches for the configured group
4. Scans the chat for images
5. Downloads images to `./downloads` folder
6. Uploads each image to S3 with timestamp prefix
7. Prints progress to console

## File Structure

```
whatsapp-mcp-2/
├── simple_monitor.py    # Main script with WhatsApp automation
├── s3_uploader.py       # S3 upload functionality
├── config.json          # Configuration file
├── requirements.txt     # Python dependencies
├── downloads/           # Temporary image storage (created automatically)
└── README_MVP.md        # This file
```

## Limitations (MVP)

- Only monitors one group
- Only downloads images (no videos, documents, audio)
- No duplicate detection (will re-upload same images)
- No error recovery or retry logic
- No persistent storage tracking
- Requires manual execution each time
- Downloads all visible images in chat (not real-time monitoring)

## Next Steps (Post-MVP)

- [ ] Monitor multiple groups
- [ ] Support all media types (videos, audio, documents)
- [ ] Add duplicate detection (database or file hashing)
- [ ] Real-time monitoring with continuous sync
- [ ] Better error handling and retry logic
- [ ] Docker containerization
- [ ] Support for Google Drive, Dropbox
- [ ] Web dashboard for management

## Troubleshooting

**Issue: "No images found"**
- Make sure you scrolled up in the chat to load images
- WhatsApp Web only loads visible images

**Issue: "Upload failed"**
- Check your AWS credentials in config.json
- Verify S3 bucket exists and IAM user has write permissions
- Check AWS region is correct

**Issue: "Can't find group"**
- Make sure group name in config.json matches exactly
- Group must be in your recent chats

## Security Notes

- Never commit `config.json` with real credentials to git
- Use IAM users with minimal S3 permissions only
- Consider using AWS credentials from environment variables

## License

MIT License - See LICENSE file for details
