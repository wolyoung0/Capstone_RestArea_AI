import requests
import pymysql
import time
import re

# ----------------- 설정 -----------------
# 네이버 API 키
NAVER_CLIENT_ID = "dm6GBOvjE6THfBRMEi5W"
NAVER_CLIENT_SECRET = "1ckwAVvELt"

# DB 접속 정보 (Spring Boot application.properties 참고)
DB_HOST = "localhost"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "1234"
DB_NAME = "road_taste" # 실제 DB 이름
# ----------------------------------------

def get_db_connection():
    return pymysql.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, db=DB_NAME, charset='utf8mb4'
    )

def search_naver_image(query):
    url = "https://openapi.naver.com/v1/search/image"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    # 정확도보다는 퀄리티(filter=medium)와 유사도(sim) 기준
    params = {"query": query, "display": 1, "sort": "sim", "filter": "medium"}
    
    try:
        res = requests.get(url, headers=headers, params=params)
        if res.status_code == 200:
            data = res.json()
            if data['items']:
                return data['items'][0]['link']
    except Exception as e:
        print(f"Error searching {query}: {e}")
    return None

def update_rest_area_images():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 이미지가 없는 휴게소 조회 (테이블명 rest_area 가정)
    # image_url 컬럼이 없다면 DB에 먼저 추가해야 함: ALTER TABLE rest_area ADD COLUMN image_url VARCHAR(1000);
    cursor.execute("SELECT rest_area_id, name FROM rest_area WHERE image_url IS NULL OR image_url = ''")
    areas = cursor.fetchall()
    
    print(f"--- 휴게소 이미지 업데이트 대상: {len(areas)}개 ---")
    
    for area_id, name in areas:
        # 검색어: "기흥휴게소 전경"
        keyword = f"{name} 전경"
        image_url = search_naver_image(keyword)
        
        if image_url:
            print(f"[UPDATE] {name}: {image_url}")
            cursor.execute("UPDATE rest_area SET image_url = %s WHERE rest_area_id = %s", (image_url, area_id))
            conn.commit()
        else:
            print(f"[FAIL] {name}")
        
        time.sleep(0.1) # API 제한 고려
        
    conn.close()

def update_food_menu_images():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 이미지가 없는 메뉴 조회 (테이블명 food_menu 가정)
    cursor.execute("SELECT menu_id, name FROM food_menu WHERE image_url IS NULL OR image_url = ''")
    menus = cursor.fetchall()
    
    print(f"--- 메뉴 이미지 업데이트 대상: {len(menus)}개 ---")
    
    for menu_id, name in menus:
        # 검색어 정제: 특수문자 제거
        clean_name = re.sub(r'\([^)]*\)', '', name).strip() # (돈가스잔치) 등 제거
        image_url = search_naver_image(clean_name)
        
        if image_url:
            print(f"[UPDATE] {clean_name}: {image_url}")
            cursor.execute("UPDATE food_menu SET image_url = %s WHERE menu_id = %s", (image_url, menu_id))
            conn.commit()
        else:
            print(f"[FAIL] {clean_name}")
            
        time.sleep(0.1)

    conn.close()

if __name__ == "__main__":
    # 1. 휴게소 이미지 업데이트
    update_rest_area_images()
    
    # 2. 메뉴 이미지 업데이트
    update_food_menu_images()