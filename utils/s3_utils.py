import os
import boto3
from botocore.exceptions import NoCredentialsError

def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_REGION')
    )

def upload_file_to_s3(file_path, bucket, object_name=None):
    s3 = get_s3_client()
    if object_name is None:
        object_name = os.path.basename(file_path)
    try:
        s3.upload_file(file_path, bucket, object_name)
        url = f'https://{bucket}.s3.{os.getenv("AWS_REGION")}.amazonaws.com/{object_name}'
        return url
    except NoCredentialsError:
        raise Exception('S3 credentials not available')
    except Exception as e:
        raise Exception(f'Failed to upload to S3: {e}') 