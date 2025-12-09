from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional, Dict
import csv
import io

# --- 1. 데이터 로드 및 전처리 ---

# 첨부해주신 CSV 데이터를 문자열로 하드코딩하여 로드합니다. (실제 환경에서는 파일에서 읽어옵니다)
csv_data = """기준년월,휴게소내판매순위,휴게소코드,휴게소명,매장코드,매장명,판매상품SEQ,판매상품명
2025-11,1,S000001,서울만남(부산)휴게소,0025,말죽거리한식당,1100000709,말죽거리소고기국밥
2025-11,2,S000001,서울만남(부산)휴게소,0146,돈가스잔치,1100040400,(돈가스잔치)옛날돈가스
2025-11,3,S000001,서울만남(부산)휴게소,0133,효원당,1100035951,우리밀 호두과자(14개입)
2025-11,4,S000001,서울만남(부산)휴게소,0133,효원당,1100035950,우리밀 호두과자 선물용(24개입)
2025-11,5,S000001,서울만남(부산)휴게소,0133,효원당,1100006220,(알뜰간식)우리밀 호두과자(7개입)
"""
# (CSV 데이터의 일부만 예시로 넣었으나, 실제로는 전체 데이터를 로드해야 합니다)

# 판매 순위 조회를 위한 맵 (Key: 휴게소ID + 메뉴명, Value: 순위)
sales_rank_map: Dict[str, int] = {}

def load_sales_data():
    # 실제로는 파일 읽기: with open("sales_data.csv", "r") as f: ...
    f = io.StringIO(csv_data)
    reader = csv.DictReader(f)
    for row in reader:
        # 휴게소 코드와 메뉴명을 키로 사용하여 순위를 저장
        # 메뉴명 전처리: 공백 제거 및 소문자 변환하여 매칭 확률 높임
        key = (row['휴게소코드'], row['판매상품명'].replace(" ", ""))
        sales_rank_map[key] = int(row['휴게소내판매순위'])

# 앱 시작 시 데이터 로드
load_sales_data()


# --- 2. DTO 정의 ---

class FoodMenuDto(BaseModel):
    menuId: int
    name: str
    price: int
    isPremium: bool
    averageRating: Optional[float] = None

class RestAreaDto(BaseModel):
    restAreaId: int # ID 타입을 String으로 변경 (CSV와 매칭 위해)
    name: str
    routeName: str
    latitude: float
    longitude: float
    facilities: List[str]
    foodMenus: List[FoodMenuDto]

class RouteData(BaseModel):
    traffic_state: int
    current_time: str
    weather: str

class RecommendationRequest(BaseModel):
    route_data: RouteData
    rest_areas: List[RestAreaDto]
    user_preference: str = "meal"

class RecommendationResponse(BaseModel):
    restAreaId: int
    restAreaName: str
    recommendedMenu: str
    menuPrice: int
    score: float
    reason: str

app = FastAPI()


# --- 3. 추천 로직 헬퍼 함수 ---

def get_sales_rank(rest_area_id: str, menu_name: str) -> int:
    # 맵에서 순위 조회, 없으면 999위 반환
    key = (str(rest_area_id), menu_name.replace(" ", ""))
    return sales_rank_map.get(key, 999)

def calculate_menu_score(rest_area_id: int, menu: FoodMenuDto, route_data: RouteData, preference: str) -> (float, str):
    score = 0.0
    reasons = []
    menu_name = menu.name
    
    # 1. 판매량 점수 (가장 강력한 지표)
    rank = get_sales_rank(rest_area_id, menu_name)
    if rank <= 5:
        # 1위: 30점, 2위: 25점, ... 5위: 10점
        sales_score = 35 - (rank * 5)
        score += sales_score
        if rank == 1:
            reasons.append("🥇 이 휴게소 판매 1위")
        else:
            reasons.append(f"🔥 인기 메뉴(Top {rank})")

    # 2. 사용자 취향 점수 (필터)
    # 키워드 매칭 로직 강화
    pref_score = 0
    if preference == "spicy":
        if any(k in menu_name for k in ["매운", "짬뽕", "육개장", "순두부", "낙지", "떡볶이", "마라", "얼큰", "김치찌개"]):
            pref_score = 50
            reasons.append("화끈한 매운맛")
            
    elif preference == "kids":
        if any(k in menu_name for k in ["돈가스", "돈까스", "우동", "짜장", "함박", "소세지", "핫도그", "버거", "불고기"]):
            pref_score = 50
            reasons.append("아이들이 좋아하는")
            
    elif preference == "snack":
        if any(k in menu_name for k in ["호두", "과자", "핫도그", "소떡", "통감자", "오징어", "바", "꼬치", "샌드위치", "빵", "토스트"]):
            pref_score = 50
            reasons.append("가볍게 즐기는 간식")
            
    elif preference == "hangover":
        if any(k in menu_name for k in ["국밥", "황태", "콩나물", "북어", "해장", "라면", "우동", "탕", "찌개"]):
            pref_score = 50
            reasons.append("속 풀리는 해장")
            
    elif preference == "meal":
        # 식사는 범위가 넓으므로 점수 비중을 조금 낮춤
        if any(k in menu_name for k in ["정식", "찌개", "비빔밥", "덮밥", "곰탕", "설렁탕", "백반", "국밥"]):
            pref_score = 30
            reasons.append("든든한 한 끼")

    score += pref_score

    # 3. 날씨 기반 점수
    weather = route_data.weather.lower()
    weather_score = 0
    if any(w in weather for w in ["rain", "snow", "cloud", "overcast"]): # 흐리거나 비
        if any(k in menu_name for k in ["우동", "짬뽕", "국밥", "찌개", "전골", "탕"]):
            weather_score = 20
            reasons.append("비 오는 날엔 따뜻한 국물")
    elif any(w in weather for w in ["hot", "sun", "clear"]): # 맑거나 더움
        if any(k in menu_name for k in ["냉면", "모밀", "소바", "아이스", "빙수"]):
            weather_score = 20
            reasons.append("더위를 식혀줄 시원함")
            
    score += weather_score

    # 4. 기본 평점 반영
    rating = menu.averageRating if menu.averageRating is not None else 3.0
    score += rating * 5  # 5점 만점 기준 최대 25점

    # 5. 추천 사유 조합 (최대 2개까지만 노출하여 깔끔하게)
    # 우선순위: 사용자 취향 > 날씨 > 판매량
    final_reason = ""
    if not reasons:
        final_reason = "무난하게 즐길 수 있는 메뉴"
    else:
        # 중복 제거 및 연결
        unique_reasons = list(dict.fromkeys(reasons))
        final_reason = ", ".join(unique_reasons[:2])  # 앞의 2개 이유만 사용
        if len(unique_reasons) > 1:
             final_reason += "이에요!"
        else:
             final_reason += " 추천해요!"

    return score, final_reason


# --- 4. 메인 엔드포인트 ---

@app.post("/recommend", response_model=List[RecommendationResponse])
async def create_recommendation(request: RecommendationRequest):
    
    route_data = request.route_data
    user_pref = request.user_preference
    
    results = []
    
    for area in request.rest_areas:
        best_menu = None
        max_score = -1.0
        best_reason = ""

        # 메뉴가 없는 휴게소 건너뛰기
        if not area.foodMenus:
            continue

        for menu in area.foodMenus:
            score, reason = calculate_menu_score(area.restAreaId, menu, route_data, user_pref)
            
            # [디버깅용 로그] 실제 점수가 어떻게 계산되는지 확인
            print(f"[{area.name}] {menu.name}: {score}점 ({reason})")

            # 점수가 같으면 기존 것 유지 (먼저 나온게 우선) -> 개선: 점수가 같으면 가격이 싼 것? 등 추가 로직 가능
            if score > max_score:
                max_score = score
                best_menu = menu
                best_reason = reason
        
        if best_menu:
            results.append(RecommendationResponse(
                restAreaId=area.restAreaId,
                restAreaName=area.name,
                recommendedMenu=best_menu.name,
                menuPrice=best_menu.price,
                score=max_score,
                reason=best_reason
            ))

    # 전체 결과 중 점수가 높은 순서대로 정렬하여 반환
    results.sort(key=lambda x: x.score, reverse=True)

    return results