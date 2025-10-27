import boto3
import os
from datetime import datetime


def upload_to_s3(file_path, bucket_name, aws_access_key_id, aws_secret_access_key, region):
    """
    Upload a file to S3 bucket.

    Args:
        file_path: Local path to the file
        bucket_name: S3 bucket name
        aws_access_key_id: AWS access key
        aws_secret_access_key: AWS secret key
        region: AWS region

    Returns:
        bool: True if upload successful, False otherwise
    """
    try:
        # Create S3 client
        s3_client = boto3.client(
            's3',
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region
        )

        # Generate S3 key with timestamp to avoid overwriting
        filename = os.path.basename(file_path)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        s3_key = f"whatsapp_images/{timestamp}_{filename}"

        # Upload file
        s3_client.upload_file(file_path, bucket_name, s3_key)

        print(f"✓ Uploaded: {filename} -> s3://{bucket_name}/{s3_key}")
        return True

    except Exception as e:
        print(f"✗ Upload failed for {file_path}: {str(e)}")
        return False
