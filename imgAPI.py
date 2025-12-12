import psycopg2
import time
import random
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ==================== 설정 ====================
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "road_taste" # 본인 DB명 확인!
DB_USER = "postgres"
DB_PASSWORD = "1234"
# ============================================

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD, port=DB_PORT
    )

def setup_driver():
    """셀레니움 크롬 드라이버 설정"""
    chrome_options = Options()
    # chrome_options.add_argument("--headless")  # 브라우저 창 안 띄우려면 주석 해제
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # 네이버가 봇으로 인식하지 않게 User-Agent 설정
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def refine_keyword(raw_name):
    """검색어 최적화 (기존 로직 유지)"""
    if "휴게소" not in raw_name:
        return raw_name
    match = re.match(r'(.*?)\((.*?)\)휴게소', raw_name)
    if match:
        base_name = match.group(1).strip()
        direction = match.group(2).strip()
        return f"{base_name}휴게소 {direction}방향"
    return raw_name

def crawl_naver_selenium(driver, query):
    """셀레니움으로 네이버 검색 결과 크롤링"""
    search_url = f"https://search.naver.com/search.naver?where=nexearch&sm=top_hty&fbm=0&ie=utf8&query={query}"
    driver.get(search_url)
    
    image_url = None
    phone = None
    
    try:
        # 데이터가 로딩될 때까지 최대 3초 대기
        wait = WebDriverWait(driver, 3)
        
        # 1. 이미지 찾기 (여러가지 CSS 선택자 시도)
        # 네이버 플레이스 영역의 이미지가 로딩되길 기다림
        try:
            # Case A: 일반적인 플레이스 썸네일
            img_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".api_subject_bx .thumb_area img")))
            image_url = img_element.get_attribute("src")
        except:
            try:
                # Case B: 다른 레이아웃 (place_section)
                img_element = driver.find_element(By.CSS_SELECTOR, ".place_section .rd_thumb img")
                image_url = img_element.get_attribute("src")
            except:
                try:
                    # Case C: 이미지 탭 미리보기
                    img_element = driver.find_element(By.CSS_SELECTOR, ".img_area img")
                    image_url = img_element.get_attribute("src")
                except:
                    pass

        # 2. 전화번호 찾기 (API 없이 화면에서 긁어오기)
        try:
            # '전화번호 복사' 버튼 근처나 텍스트 찾기
            # 보통 class="tell" 또는 0507, 02 등으로 시작하는 텍스트
            tel_candidates = driver.find_elements(By.XPATH, "//*[contains(text(), '-')]")
            for cand in tel_candidates:
                text = cand.text.strip()
                # 전화번호 형식 정규식 (02-1234-5678, 031-123-4567 등)
                if re.match(r'^\d{2,3}-\d{3,4}-\d{4}$', text):
                    phone = text
                    break
        except:
            pass

    except Exception as e:
        print(f"   [Error] 크롤링 중 오류: {e}")

    return image_url, phone

def update_rest_area_data():
    conn = get_db_connection()
    cur = conn.cursor()
    driver = setup_driver() # 브라우저 실행
    
    print(">>> 업데이트 대상 휴게소를 조회합니다...")
    # 실패했거나 빈 데이터 다시 시도
    cur.execute("""
        SELECT rest_area_id, name 
        FROM rest_areas 
        ORDER BY rest_area_id ASC
    """)
    
    rows = cur.fetchall()
    total = len(rows)
    print(f">>> 총 {total}개 작업 시작 (Selenium 방식)\n")
    
    for i, (area_id, raw_name) in enumerate(rows):
        search_name = refine_keyword(raw_name)
        print(f"[{i+1}/{total}] '{search_name}' 검색 중...", end=" ", flush=True)
        
        img, tel = crawl_naver_selenium(driver, search_name)
        
        # 값이 구해진 경우에만 업데이트 (기존 값 덮어쓰기 방지 로직 필요시 수정)
        if img or tel:
            update_sql = """
                UPDATE rest_areas 
                SET 
                    image_url = COALESCE(%s, image_url), 
                    tel = COALESCE(%s, tel)
                WHERE rest_area_id = %s
            """
            cur.execute(update_sql, (img, tel, area_id))
            conn.commit()
        
        res_img = "O" if img else "X"
        res_tel = tel if tel else "X"
        print(f"-> [이미지: {res_img}, 전화: {res_tel}]")
        
        # 봇 탐지 방지 딜레이
        time.sleep(random.uniform(1.0, 2.0))

    driver.quit() # 브라우저 종료
    cur.close()
    conn.close()
    print("\n>>> 완료!")

if __name__ == "__main__":
    update_rest_area_data()