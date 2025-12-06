import requests
import pandas as pd
from sqlalchemy import create_engine, text
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================================
# [설정] API 키와 DB 접속 정보
# ==========================================
API_KEY = "7208914977"
DB_URL = "postgresql://postgres:1234@localhost:5432/road_taste"
engine = create_engine(DB_URL)

# ==========================================
# 세션 생성 (재시도 기능)
# ==========================================
def get_session():
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# ==========================================
# 데이터 수집 함수 (중복 체크 및 전체 수집)
# ==========================================
def fetch_api_data(url):
    all_data = []
    seen_items = set() 
    page_no = 1
    session = get_session()
    
    # 로그용 이름 추출
    api_name = url.split('/')[-1]
    if 'apiId=' in url:
        api_name = url.split('apiId=')[-1][:4]
        
    print(f"📡 요청 시작: {api_name}")
    
    while True:
        try:
            params = {"key": API_KEY, "type": "json", "numOfRows": 99, "pageNo": page_no}
            res = session.get(url, params=params, timeout=10)
            
            try:
                data = res.json()
            except ValueError:
                print(f"⚠️ [Page {page_no}] JSON 변환 실패. (건너뜀)")
                break

            if 'list' not in data or not data['list']:
                break
            
            items = data['list']
            
            # 중복 체크
            new_items = []
            for item in items:
                item_signature = str(item)
                if item_signature in seen_items:
                    continue
                seen_items.add(item_signature)
                new_items.append(item)
            
            if not new_items:
                print(f"   ✋ [Page {page_no}] 더 이상 새로운 데이터가 없습니다. (수집 종료)")
                break

            all_data.extend(new_items)
            print(f"   - page {page_no} 수집 ({len(new_items)}건 신규)")
            
            page_no += 1
            time.sleep(0.5)

        except Exception as e:
            print(f"❌ [Page {page_no}] 에러 발생: {e}")
            break
            
    return pd.DataFrame(all_data)

# ==========================================
# 메인 마이그레이션 실행
# ==========================================
def run_migration():
    # ------------------------------------------------
    # 1. 휴게소 기본 정보 (hiwaySvarInfoList)
    # ------------------------------------------------
    print("\n[1/4] 휴게소 기본 정보(hiwaySvarInfoList) 수집 중...")
    url_base = "https://data.ex.co.kr/openapi/restinfo/hiwaySvarInfoList"
    df_base = fetch_api_data(url_base)
    
    # ------------------------------------------------
    # 2. 휴게소 위치 정보 (locationinfoRest)
    # ------------------------------------------------
    print("\n[2/4] 휴게소 좌표 정보(locationinfoRest) 수집 중...")
    url_loc = "https://data.ex.co.kr/openapi/locationinfo/locationinfoRest"
    df_loc = fetch_api_data(url_loc)

    # ------------------------------------------------
    # 3. 정보 병합 및 DB 저장 (rest_areas)
    # ------------------------------------------------
    if not df_base.empty:
        df_save = pd.DataFrame()

        # (1) 기본 정보에서 코드 찾기
        base_code_col = 'svarCd' if 'svarCd' in df_base.columns else 'stdRestCd'
        if base_code_col not in df_base.columns:
            base_code_col = 'unitCode'
            
        df_base[base_code_col] = df_base[base_code_col].astype(str)
        
        # (2) 위치 정보 매핑 준비
        loc_map = {}
        if not df_loc.empty:
            for _, row in df_loc.iterrows():
                lng = row.get('xValue')
                lat = row.get('yValue')
                if 'stdRestCd' in row and row['stdRestCd']:
                    loc_map[str(row['stdRestCd'])] = (lng, lat)
                if 'unitCode' in row and row['unitCode']:
                    loc_map[str(row['unitCode'])] = (lng, lat)
                    
        def get_coords(code):
            return loc_map.get(code, (0, 0))

        # (3) 데이터 프레임 생성
        df_save['service_area_code'] = df_base[base_code_col]
        
        # 이름
        if 'svarNm' in df_base.columns:
            df_save['name'] = df_base['svarNm']
        else:
            df_save['name'] = df_base.get('unitName', '이름없음')

        # [!!! 중요 !!!] 주유소, 충전소 데이터 제외 로직
        # 이름에 '주유소' 또는 '충전소'가 포함된 행을 삭제합니다.
        print(f"   ℹ️ 필터링 전: {len(df_save)}건")
        df_save = df_save[~df_save['name'].str.contains('주유소|충전소', na=False)]
        print(f"   ℹ️ 필터링 후(휴게소만): {len(df_save)}건")

        # 노선명
        if 'routeNm' in df_base.columns:
             df_save['route_name'] = df_base['routeNm']
        else:
             df_save['route_name'] = df_base.get('routeName', '정보없음')

        # 방향, 주소
        df_save['direction'] = df_base.get('routeDir', df_base.get('gudClssNm', '양방향'))
        df_save['address'] = df_base.get('svarAddr', df_base.get('rprsTelNo', ''))
        
        # 좌표 매핑
        coords = df_save['service_area_code'].apply(get_coords)
        df_save['longitude'] = coords.apply(lambda x: pd.to_numeric(x[0], errors='coerce') if x else 0).fillna(0)
        df_save['latitude'] = coords.apply(lambda x: pd.to_numeric(x[1], errors='coerce') if x else 0).fillna(0)

        df_save['created_at'] = pd.Timestamp.now()
        df_save['updated_at'] = pd.Timestamp.now()
        
        try:
            df_save.to_sql('rest_areas', engine, if_exists='append', index=False)
            print(f"✅ 휴게소 {len(df_save)}개 저장 완료.")
        except Exception as e:
            print(f"⚠️ 저장 중 에러: {e}")
    
    # ------------------------------------------------
    # ID 매핑 (API코드 -> DB ID)
    # ------------------------------------------------
    print("🔄 ID 매핑 정보 로딩 중...")
    with engine.connect() as conn:
        # 이미 DB에 저장된 휴게소만 가져오므로 주유소 ID는 자연스럽게 없음
        query = text("SELECT service_area_code, rest_area_id FROM rest_areas")
        mapping_df = pd.read_sql(query, conn)
    
    mapping_df['service_area_code'] = mapping_df['service_area_code'].astype(str)
    code_to_id = dict(zip(mapping_df['service_area_code'], mapping_df['rest_area_id']))
    
    print(f"   ℹ️ 매핑 준비 완료 (총 {len(code_to_id)}개 휴게소)")

    # ------------------------------------------------
    # 3. 음식 메뉴 (restBestfoodList)
    # ------------------------------------------------
    print("\n[3/4] 음식 메뉴(food_menus) 처리 중...")
    url_food = "https://data.ex.co.kr/openapi/restinfo/restBestfoodList"
    df_food = fetch_api_data(url_food)

    if not df_food.empty:
        rest_code_col = 'stdRestCd' if 'stdRestCd' in df_food.columns else 'svarCd'
        if rest_code_col not in df_food.columns:
            rest_code_col = 'unitCode' if 'unitCode' in df_food.columns else None

        if rest_code_col:
            df_food[rest_code_col] = df_food[rest_code_col].astype(str)
            df_save = pd.DataFrame()
            
            # 여기서 주유소 코드는 code_to_id 딕셔너리에 없으므로 자동으로 걸러짐 (NaN이 됨)
            df_save['rest_area_id'] = df_food[rest_code_col].map(code_to_id)
            
            # 주유소 메뉴나 매핑 안 된 데이터 삭제
            df_save = df_save.dropna(subset=['rest_area_id'])
            
            if not df_save.empty:
                name_col = 'foodName' if 'foodName' in df_food.columns else 'foodNm'
                df_save['name'] = df_food.get(name_col, '이름없음')
                
                cost_col = 'foodCost' if 'foodCost' in df_food.columns else 'stdFoodCost'
                df_save['price'] = pd.to_numeric(df_food.get(cost_col), errors='coerce')
                
                df_save['description'] = df_food.get('etc', '')
                df_save['is_premium'] = df_food.get('bestfoodyn', 'N') == 'Y'
                df_save['created_at'] = pd.Timestamp.now()
                df_save['updated_at'] = pd.Timestamp.now()
                
                df_save.to_sql('food_menus', engine, if_exists='append', index=False)
                print(f"✅ 음식 메뉴 {len(df_save)}개 저장 완료.")

    # ------------------------------------------------
    # 4. 편의 시설 (restConvList)
    # ------------------------------------------------
    print("\n[4/4] 편의 시설(rest_area_facilities) 처리 중...")
    url_conv = "https://data.ex.co.kr/openapi/restinfo/restConvList"
    df_conv = fetch_api_data(url_conv)

    if not df_conv.empty:
        conv_code_col = 'stdRestCd' if 'stdRestCd' in df_conv.columns else 'svarCd'
        if conv_code_col not in df_conv.columns:
            conv_code_col = 'unitCode' if 'unitCode' in df_conv.columns else None
        
        if conv_code_col:
            df_conv[conv_code_col] = df_conv[conv_code_col].astype(str)
            
            df_save = pd.DataFrame()
            # 마찬가지로 주유소 편의시설은 여기서 자동으로 제외됨
            df_save['rest_area_id'] = df_conv[conv_code_col].map(code_to_id)
            df_save = df_save.dropna(subset=['rest_area_id'])
            
            if not df_save.empty:
                if 'psName' in df_conv.columns:
                    df_save['facility_name'] = df_conv['psName']
                elif 'conveniName' in df_conv.columns:
                    df_save['facility_name'] = df_conv['conveniName']
                else:
                    df_save['facility_name'] = '이름없음'

                df_save['description'] = df_conv.get('psDesc', df_conv.get('conveniDesc', ''))
                df_save['created_at'] = pd.Timestamp.now()
                df_save['updated_at'] = pd.Timestamp.now()
                
                df_save.to_sql('rest_area_facilities', engine, if_exists='append', index=False)
                print(f"✅ 편의 시설 {len(df_save)}개 저장 완료.")

if __name__ == "__main__":
    run_migration()