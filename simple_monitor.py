import json
import os
import time
from playwright.sync_api import sync_playwright
from s3_uploader import upload_to_s3


def load_config():
    """Load configuration from config.json"""
    with open('config.json', 'r') as f:
        return json.load(f)


def download_images(page, download_dir):
    """
    Download all images from the current WhatsApp chat.

    Args:
        page: Playwright page object
        download_dir: Directory to save downloaded images

    Returns:
        list: Paths of downloaded images
    """
    downloaded_files = []

    try:
        # Find all image elements in the chat
        images = page.locator('img[src*="blob:"]').all()

        print(f"Found {len(images)} images in chat")

        for idx, img in enumerate(images):
            try:
                # Click on the image to open it
                img.click()
                time.sleep(1)

                # Wait for the download button to appear
                download_btn = page.locator('[data-icon="download"]').first
                if download_btn.is_visible():
                    # Click download button
                    with page.expect_download() as download_info:
                        download_btn.click()

                    download = download_info.value
                    file_path = os.path.join(download_dir, download.suggested_filename)
                    download.save_as(file_path)

                    downloaded_files.append(file_path)
                    print(f"Downloaded: {download.suggested_filename}")

                # Close the image viewer
                close_btn = page.locator('[data-icon="x-viewer"]').first
                if close_btn.is_visible():
                    close_btn.click()
                    time.sleep(0.5)

            except Exception as e:
                print(f"Error downloading image {idx}: {str(e)}")
                # Try to close any open viewer
                try:
                    page.keyboard.press('Escape')
                except:
                    pass
                continue

    except Exception as e:
        print(f"Error finding images: {str(e)}")

    return downloaded_files


def main():
    """Main function to monitor WhatsApp group and upload images to S3"""
    # Load configuration
    config = load_config()
    group_name = config['whatsapp']['group_name']
    bucket_name = config['aws']['bucket_name']
    aws_access_key_id = config['aws']['access_key_id']
    aws_secret_access_key = config['aws']['secret_access_key']
    region = config['aws']['region']

    # Create download directory
    download_dir = os.path.join(os.getcwd(), 'downloads')
    os.makedirs(download_dir, exist_ok=True)

    print("=" * 60)
    print("WhatsApp Cloud Sync - MVP")
    print("=" * 60)
    print(f"Monitoring group: {group_name}")
    print(f"S3 Bucket: {bucket_name}")
    print("=" * 60)

    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # Navigate to WhatsApp Web
        print("\nOpening WhatsApp Web...")
        page.goto('https://web.whatsapp.com')

        # Wait for user to scan QR code and login
        print("\nPlease scan the QR code to login to WhatsApp Web...")
        print("Waiting for login...")

        # Wait for the chat list to appear (means user is logged in)
        page.wait_for_selector('[data-testid="chat-list"]', timeout=120000)
        print("✓ Logged in successfully!")

        # Search for the group
        print(f"\nSearching for group: {group_name}")
        search_box = page.locator('[data-testid="chat-list-search"]')
        search_box.click()
        search_box.fill(group_name)
        time.sleep(2)

        # Click on the first search result
        first_result = page.locator('[data-testid="cell-frame-container"]').first
        first_result.click()
        time.sleep(2)

        print(f"✓ Opened group: {group_name}")

        # Download images from the chat
        print("\nScanning for images...")
        downloaded_files = download_images(page, download_dir)

        # Upload to S3
        if downloaded_files:
            print(f"\nUploading {len(downloaded_files)} images to S3...")
            for file_path in downloaded_files:
                upload_to_s3(
                    file_path,
                    bucket_name,
                    aws_access_key_id,
                    aws_secret_access_key,
                    region
                )

            print(f"\n✓ Process complete! Uploaded {len(downloaded_files)} images")
        else:
            print("\nNo images found in the chat")

        # Clean up
        input("\nPress Enter to close the browser...")
        browser.close()


if __name__ == "__main__":
    main()
