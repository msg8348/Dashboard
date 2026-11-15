"""학구도 받아서 몇 단지 배정학교 확인."""
import os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import schoolzone
os.makedirs("store", exist_ok=True)
z = schoolzone.load("store", "26", datetime.now())
print("구역", len(z))
for n, x, y in [("더비치푸르지오써밋", 129.108129, 35.136666), ("베뉴브", 129.140522, 35.168461), ("남천자이", 129.112897, 35.140259), ("래미안장전", 129.087109, 35.226269)]:
    print(n, schoolzone.schools_at(z, x, y))
