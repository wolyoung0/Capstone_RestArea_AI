from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional

# --- 1. DTO 정의 ---

class FoodMenuDto(BaseModel):
    menuId: int
    name: str
    price: int
    isPremium: bool
    averageRating: Optional[float] = None

class RestAreaDto(BaseModel):
    restAreaId: int
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
    # [수정] 프론트엔드에서 선택한 필터 (예: "spicy", "kids", "meal" 등)
    # 값이 안 올 경우를 대비해 기본값 설정
    user_preference: str = "meal" 

class RecommendationResponse(BaseModel):
    restAreaId: int
    restAreaName: str
    recommendedMenu: str
    menuPrice: int
    score: float
    reason: str

app = FastAPI()

# --- 2. 추천 로직 헬퍼 함수 ---

def calculate_menu_score(menu: FoodMenuDto, route_data: RouteData, preference: str) -> (float, str):
    score = 0.0
    reasons = []
    menu_name = menu.name

    # (1) 기본 점수
    rating = menu.averageRating if menu.averageRating is not None else 3.0
    score += rating * 10 

    # (2) 프리미엄 메뉴 가산점
    if menu.isPremium:
        score += 5
        # reasons.append("프리미엄") # 너무 흔하면 사유에서 뺌

    # (3) [핵심 수정] 사용자 선택 필터(preference) 반영 로직
    # 사용자가 선택한 건 가장 중요하므로 점수를 크게(50점) 줍니다.
    
    if preference == "spicy":  # 매운맛
        if any(keyword in menu_name for keyword in ["매운", "짬뽕", "육개장", "순두부", "낙지", "떡볶이", "마라"]):
            score += 50
            reasons.append("화끈한 매운맛")
            
    elif preference == "kids": # 어린이 추천
        if any(keyword in menu_name for keyword in ["돈가스", "돈까스", "우동", "짜장", "함박", "소세지", "핫도그"]):
            score += 50
            reasons.append("아이들이 좋아하는")
            
    elif preference == "snack": # 간식
        if any(keyword in menu_name for keyword in ["호두과자", "핫도그", "소떡", "통감자", "오징어", "바", "꼬치", "샌드위치"]):
            score += 50
            reasons.append("가볍게 즐기는 간식")
            
    elif preference == "sweet": # 달콤한 맛
        if any(keyword in menu_name for keyword in ["아이스", "케이크", "초코", "라떼", "스무디", "도넛", "와플"]):
            score += 50
            reasons.append("달콤한 당 충전")
            
    elif preference == "hangover": # 해장
        if any(keyword in menu_name for keyword in ["국밥", "황태", "콩나물", "북어", "해장", "라면", "우동"]):
            score += 50
            reasons.append("속 풀리는 해장")
            
    elif preference == "meal": # 든든한 식사
        if any(keyword in menu_name for keyword in ["정식", "찌개", "비빔밥", "덮밥", "곰탕", "설렁탕", "백반"]):
            score += 30 # 식사는 범위가 넓어서 점수를 조금 낮게 조정
            reasons.append("든든한 한 끼")

    # (4) 날씨 기반 (기존 유지)
    weather = route_data.weather.lower()
    if "rain" in weather or "snow" in weather:
        if any(keyword in menu_name for keyword in ["우동", "짬뽕", "국밥", "찌개"]):
            score += 10
            reasons.append("비 오는 날 국물")
    elif "hot" in weather or "sun" in weather:
        if any(keyword in menu_name for keyword in ["냉면", "모밀", "소바", "아이스"]):
            score += 10
            reasons.append("더운 날 시원하게")

    # (5) 교통 상황 (기존 유지)
    if route_data.traffic_state >= 3:
        if any(keyword in menu_name for keyword in ["호두과자", "핫도그", "바", "김밥"]):
            score += 5
            reasons.append("차 막힐 땐 간편식")

    return score, ", ".join(reasons)


# --- 3. 메인 엔드포인트 ---

@app.post("/recommend", response_model=List[RecommendationResponse])
async def create_recommendation(request: RecommendationRequest):
    
    route_data = request.route_data
    user_pref = request.user_preference # [수정] 요청에서 필터 정보 가져오기
    
    results = []
    
    for area in request.rest_areas:
        best_menu = None
        max_score = -1.0
        best_reason = ""

        if not area.foodMenus:
            continue

        for menu in area.foodMenus:
            # [수정] user_pref 전달
            score, reason = calculate_menu_score(menu, route_data, user_pref)
            
            if score > max_score:
                max_score = score
                best_menu = menu
                best_reason = reason
        
        if best_menu:
            # 필터에 맞는 메뉴가 아예 없으면 점수가 낮아서 추천이 이상할 수 있음.
            # 하지만 max_score 로직 때문에 그나마 점수가 높은게 나감.
            
            results.append(RecommendationResponse(
                restAreaId=area.restAreaId,
                restAreaName=area.name,
                recommendedMenu=best_menu.name,
                menuPrice=best_menu.price,
                score=max_score,
                reason=best_reason if best_reason else "AI 추천 인기 메뉴"
            ))

    # 점수순 정렬
    results.sort(key=lambda x: x.score, reverse=True)

    return results