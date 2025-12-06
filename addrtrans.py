import pandas as pd
from sqlalchemy import create_engine, text
from geopy.geocoders import Nominatim
import time

# 1. DB 연결
DB_URL = "postgresql://postgres:1234@localhost:5432/road_taste"
engine = create_engine(DB_URL)

# 2. 지오코딩 도구 생성 (무료 오픈소스 지도 사용)
# user_agent에는 본인의 프로젝트 이름이나 이메일을 적어주세요.
geolocator = Nominatim(user_agent="my_capstone_project")

def update_missing_coordinates():
    print("🔄 좌표 없는 데이터 조회 중...")
    
    # 좌표가 0인 데이터만 가져오기
    query = text("SELECT rest_area_id, address FROM rest_areas WHERE latitude = 0 OR longitude = 0")
    
    with engine.connect() as conn:
        df_missing = pd.read_sql(query, conn)
    
    print(f"   총 {len(df_missing)}개의 좌표를 찾습니다.")
    
    success_count = 0
    
    for index, row in df_missing.iterrows():
        rid = row['rest_area_id']
        addr = row['address']
        
        try:
            # 주소로 좌표 찾기 (GeoCoding)
            location = geolocator.geocode(addr)
            
            if location:
                # DB 업데이트
                update_sql = text("""
                    UPDATE rest_areas 
                    SET latitude = :lat, longitude = :lng, updated_at = NOW()
                    WHERE rest_area_id = :rid
                """)
                
                with engine.begin() as conn:
                    conn.execute(update_sql, {"lat": location.latitude, "lng": location.longitude, "rid": rid})
                
                print(f"   ✅ [성공] {addr} -> {location.latitude}, {location.longitude}")
                success_count += 1
            else:
                print(f"   ⚠️ [실패] 주소 불명확: {addr}")
                
            # 무료 API는 너무 빨리 요청하면 차단되므로 1초 쉽니다.
            time.sleep(1) 
            
        except Exception as e:
            print(f"   ❌ 에러: {e}")

    print(f"\n🎉 작업 완료! {len(df_missing)}개 중 {success_count}개 변환 성공")

if __name__ == "__main__":
    update_missing_coordinates()