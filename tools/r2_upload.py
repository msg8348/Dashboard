"""R2 업로드: 폴더 안 파일 중 바뀐 것만 올림 (내용 해시를 store/r2_manifest.json 에 기록).

    python tools/r2_upload.py r2out store/r2_manifest.json
환경변수: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET(기본 nextdoorprice-data)
"""
import hashlib
import json
import mimetypes
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.config import Config

src, man_path = sys.argv[1], sys.argv[2]
bucket = os.environ.get("R2_BUCKET", "nextdoorprice-data")
s3 = boto3.client("s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                  aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                  region_name="auto", config=Config(retries={"max_attempts": 5, "mode": "standard"}, max_pool_connections=32))
man = {}
if os.path.exists(man_path):
    with open(man_path) as f:
        man = json.load(f)
todo = []
for root, _, files in os.walk(src):
    for fn in files:
        p = os.path.join(root, fn)
        key = os.path.relpath(p, src).replace(os.sep, "/")
        with open(p, "rb") as f:
            data = f.read()
        h = hashlib.md5(data).hexdigest()
        if man.get(key) != h:
            todo.append((key, data, h))


def put(item):
    key, data, h = item
    ct = mimetypes.guess_type(key)[0] or "application/octet-stream"
    if ct == "application/json":
        ct += "; charset=utf-8"
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=ct, CacheControl="public, max-age=300")
    return key, h


done = 0
with ThreadPoolExecutor(24) as ex:
    for key, h in ex.map(put, todo):
        man[key] = h
        done += 1
with open(man_path, "w") as f:
    json.dump(man, f, separators=(",", ":"))
print(f"☁️ R2 업로드: 바뀐 파일 {done}개 (전체 {len(man)}개)")
