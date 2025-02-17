import streamlit as st
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import folium
from folium import plugins
import requests
import numpy as np
from datetime import datetime, timedelta
import pandas as pd
from streamlit_folium import st_folium
import time
from io import BytesIO

st.set_page_config(
    page_title="سیستم مسیریابی هوشمند",
    page_icon="🚚",
    layout="wide"
)

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700&display=swap');
    
    * {
        font-family: 'Vazirmatn', sans-serif !important;
    }
    
    .main {
        background-color: #f8f9fa;
    }
    
    .stButton>button {
        background-color: #1e88e5;
        color: white;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        font-weight: bold;
        width: 100%;
        transition: all 0.3s ease;
    }
    
    .stButton>button:hover {
        background-color: #1565c0;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    
    .css-1d391kg, .css-12oz5g7 {
        direction: rtl;
        text-align: right;
    }
    
    .metric-card {
        background-color: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        text-align: center;
    }
    
    .metric-value {
        font-size: 1.5rem;
        font-weight: bold;
        color: #1e88e5;
    }
    
    .metric-label {
        color: #666;
        font-size: 0.9rem;
    }
    
    h1, h2, h3 {
        color: #1a237e;
        font-weight: bold;
        text-align: right;
    }
    
    .stAlert {
        direction: rtl;
        text-align: right;
    }
    
    .folium-map {
        border-radius: 8px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    
    .dataframe {
        direction: rtl;
        text-align: right;
    }
    
    div[data-testid="stMetricValue"] {
        direction: ltr;
    }
    
    .stTextInput>div>div>input {
        direction: rtl;
        text-align: right;
    }
    
    .stNumberInput>div>div>input {
        direction: rtl;
        text-align: right;
    }
    </style>
    """, unsafe_allow_html=True)

class RouteOptimizer:
    def __init__(self, api_key):
        self.api_key = api_key
        self.headers = {'Api-Key': self.api_key}

    def get_route_neshan(self, start_coords, end_coords):
        """دریافت مسیر از API نشان"""
        url = "https://api.neshan.org/v4/direction"
        
        origin = f"{start_coords[0]},{start_coords[1]}"
        destination = f"{end_coords[0]},{end_coords[1]}"
        
        params = {
            'type': 'car',
            'origin': origin,
            'destination': destination
        }
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            if response.status_code == 200:
                data = response.json()
                if 'routes' in data and data['routes']:
                    route = data['routes'][0]
                    if 'legs' in route and route['legs']:
                        leg = route['legs'][0]
                        distance = leg['distance']['value']
                        duration = leg['duration']['value']
                        
                        route_coords = []
                        for step in leg['steps']:
                            if 'start_location' in step:
                                route_coords.append([
                                    step['start_location'][1],
                                    step['start_location'][0]
                                ])
                        
                        if leg['steps'] and 'end_location' in leg['steps'][-1]:
                            route_coords.append([
                                leg['steps'][-1]['end_location'][1],
                                leg['steps'][-1]['end_location'][0]
                            ])
                        
                        return route_coords, distance, duration, leg['steps']
            
            st.warning(f"خطا در دریافت مسیر از {origin} به {destination}")
            return None, None, None, None
                
        except Exception as e:
            st.error(f"خطا در ارتباط با API نشان: {str(e)}")
            return None, None, None, None

    def create_distance_time_matrices(self, locations):
        """ایجاد ماتریس‌های فاصله و زمان"""
        size = len(locations)
        distance_matrix = np.zeros((size, size))
        time_matrix = np.zeros((size, size))
        
        progress_text = st.empty()
        progress_bar = st.progress(0)
        total = size * (size - 1) // 2
        count = 0
        
        try:
            for i in range(size):
                for j in range(i + 1, size):
                    count += 1
                    progress_text.text(f"محاسبه فواصل... {count}/{total}")
                    progress_bar.progress(count/total)
                    
                    route_coords, distance, duration, _ = self.get_route_neshan(
                        locations[i], locations[j])
                    
                    if distance is not None and duration is not None:
                        distance_matrix[i][j] = distance_matrix[j][i] = distance
                        time_matrix[i][j] = time_matrix[j][i] = duration
                    else:
                        st.error(f"خطا در دریافت فاصله بین نقاط {i+1} و {j+1}")
                        return None, None
                    
                    time.sleep(0.5)  
            
            progress_text.empty()
            progress_bar.empty()
            return distance_matrix.astype(int), time_matrix.astype(int)
        
        except Exception as e:
            st.error(f"خطا در ایجاد ماتریس‌ها: {str(e)}")
            return None, None

    def create_route_map(self, locations, route_points, location_names, time_matrix, station_time, start_time_str):
        """ایجاد نقشه مسیر با جزئیات"""
        try:
            center_lat = np.mean([loc[0] for loc in locations])
            center_lng = np.mean([loc[1] for loc in locations])
            m = folium.Map(location=[center_lat, center_lng], zoom_start=12)

            current_time = datetime.strptime(start_time_str, "%H:%M")
            arrival_times = [start_time_str]

            colors = ['#1a237e', '#0d47a1', '#1565c0', '#1976d2', '#1e88e5']

            for i in range(len(route_points)-1):
                start = locations[route_points[i]]
                end = locations[route_points[i+1]]
                route_coords, distance, duration, steps = self.get_route_neshan(start, end)
                
                if i > 0:
                    current_time += timedelta(seconds=station_time)
                if duration:
                    current_time += timedelta(seconds=int(duration))
                arrival_times.append(current_time.strftime("%H:%M"))
                
                if route_coords:
                    folium.PolyLine(
                        route_coords,
                        weight=4,
                        color=colors[i % len(colors)],
                        opacity=0.8,
                        popup=f"""
                        <div dir="rtl" style="font-family: Vazirmatn, sans-serif; text-align: right;">
                            <b>مسیر {i+1}:</b><br>
                            از: {location_names[route_points[i]]}<br>
                            به: {location_names[route_points[i+1]]}<br>
                            زمان حرکت: {arrival_times[i]}<br>
                            زمان رسیدن: {arrival_times[i+1]}<br>
                            مدت سفر: {duration/60:.0f} دقیقه<br>
                            فاصله: {distance/1000:.1f} کیلومتر
                        </div>
                        """
                    ).add_to(m)

            for i, point_idx in enumerate(route_points):
                icon_color = 'red' if i == 0 else ('green' if i == len(route_points)-1 else 'blue')
                folium.Marker(
                    locations[point_idx],
                    popup=folium.Popup(
                        f"""
                        <div dir="rtl" style="font-family: Vazirmatn, sans-serif; text-align: right;">
                            <b>ایستگاه {i+1}: {location_names[point_idx]}</b><br>
                            زمان رسیدن: {arrival_times[i]}<br>
                            {'نقطه شروع' if i == 0 else f'زمان توقف: {station_time//60} دقیقه'}
                        </div>
                        """,
                        max_width=300
                    ),
                    icon=folium.Icon(color=icon_color)
                ).add_to(m)

            folium.LayerControl().add_to(m)
            plugins.Fullscreen().add_to(m)
            plugins.MousePosition().add_to(m)
            
            return m, arrival_times
            
        except Exception as e:
            st.error(f"خطا در ایجاد نقشه: {str(e)}")
            return None, None

def main():
    st.title("🚚 سیستم مسیریابی هوشمند")
    
    if 'results' not in st.session_state:
        st.session_state.results = None
    if 'map_data' not in st.session_state:
        st.session_state.map_data = None
    
    api_key = st.text_input("کلید API نشان:", value="Your Api Key", type="password", key="api_key")
    
    if not api_key:
        st.warning("لطفاً کلید API نشان را وارد کنید")
        return
        
    optimizer = RouteOptimizer(api_key)
    
    col_left, col_right = st.columns([1, 2])
    
    with col_left:
        st.subheader("⚙️ تنظیمات")
        station_time = st.number_input("زمان توقف در هر ایستگاه (دقیقه):", 
                                     min_value=1, value=15, key="station_time") * 60
        start_time = st.time_input("زمان شروع:", value=datetime.strptime("08:00", "%H:%M"), key="start_time")
        start_time_str = start_time.strftime("%H:%M")

    with col_right:
        st.subheader("📍 اطلاعات نقاط")
        
        uploaded_file = st.file_uploader(
            "فایل اکسل نمایندگی‌ها را آپلود کنید",
            type=['xlsx'],
            key="excel_uploader"
        )
        
        locations = []
        location_names = []
        
        st.markdown("#### 🏠 نقطه شروع")
        start_name = st.text_input("نام نقطه شروع:", value="دفتر مرکزی", key="start_name")
        col_start_1, col_start_2 = st.columns(2)
        with col_start_1:
            start_lat = st.number_input(
                "عرض جغرافیایی نقطه شروع:",
                value=35.6997,
                format="%.7f",
                key="start_lat"
            )
        with col_start_2:
            start_lng = st.number_input(
                "طول جغرافیایی نقطه شروع:",
                value=51.3380,
                format="%.7f",
                key="start_lng"
            )
        
        if start_name and start_lat and start_lng:
            locations.append((start_lat, start_lng))
            location_names.append(start_name)
        
        if uploaded_file is not None:
            try:
                df = pd.read_excel(uploaded_file)
                
                required_columns = ['name', 'lat', 'lng']
                if not all(col in df.columns for col in required_columns):
                    st.error("فایل اکسل باید شامل ستون‌های 'name'، 'lat' و 'lng' باشد.")
                    return
                
                st.subheader("📋 لیست نمایندگی‌های موجود")
                st.dataframe(df, key="branches_df")
                
                st.subheader("🔍 انتخاب نمایندگی‌ها")
                selected_branches = st.multiselect(
                    "نمایندگی‌های مورد نظر را انتخاب کنید:",
                    options=df['name'].tolist(),
                    key="branch_selector"
                )
                
                if selected_branches:
                    selected_df = df[df['name'].isin(selected_branches)]
                    for _, row in selected_df.iterrows():
                        locations.append((float(row['lat']), float(row['lng'])))
                        location_names.append(str(row['name']))
                    
                    st.success(f"تعداد {len(selected_branches)} نمایندگی انتخاب شد.")
                    
                    st.subheader("📍 نمایندگی‌های انتخاب شده")
                    selected_info = pd.DataFrame({
                        'نام نمایندگی': selected_branches,
                        'عرض جغرافیایی': selected_df['lat'].values,
                        'طول جغرافیایی': selected_df['lng'].values
                    })
                    st.dataframe(selected_info, key="selected_branches_df")
                
            except Exception as e:
                st.error(f"خطا در خواندن فایل اکسل: {str(e)}")
                return

    if st.button("🔍 محاسبه مسیر بهینه", key="calculate_button"):
        if len(locations) < 2:
            st.error("حداقل دو نقطه باید وارد شود")
            return
            
        with st.spinner('در حال محاسبه مسیر بهینه...'):
            distance_matrix, time_matrix = optimizer.create_distance_time_matrices(locations)
            
            if distance_matrix is None or time_matrix is None:
                st.error("خطا در محاسبه ماتریس‌های فاصله و زمان")
                return

            manager = pywrapcp.RoutingIndexManager(len(locations), 1, 0)
            routing = pywrapcp.RoutingModel(manager)

            def time_callback(from_index, to_index):
                from_node = manager.IndexToNode(from_index)
                to_node = manager.IndexToNode(to_index)
                return time_matrix[from_node][to_node]

            transit_callback_index = routing.RegisterTransitCallback(time_callback)
            routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

            routing.AddDimension(
                transit_callback_index,
                0,
                24 * 3600,
                True,
                'Time'
            )

            search_parameters = pywrapcp.DefaultRoutingSearchParameters()
            search_parameters.first_solution_strategy = (
                routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
            search_parameters.local_search_metaheuristic = (
                routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
            search_parameters.time_limit.seconds = 30

            solution = routing.SolveWithParameters(search_parameters)

            if solution:
                route_points = []
                index = routing.Start(0)
                while not routing.IsEnd(index):
                    route_points.append(manager.IndexToNode(index))
                    index = solution.Value(routing.NextVar(index))
                route_points.append(manager.IndexToNode(index))

                total_time = 0
                total_distance = 0
                for i in range(len(route_points)-1):
                    from_node = route_points[i]
                    to_node = route_points[i+1]
                    total_time += time_matrix[from_node][to_node]
                    total_distance += distance_matrix[from_node][to_node]
                    if i > 0:
                        total_time += station_time

                st.session_state.results = {
                    'route_points': route_points,
                    'total_time': total_time,
                    'total_distance': total_distance,
                    'distance_matrix': distance_matrix,
                    'time_matrix': time_matrix,
                    'location_names': location_names,
                    'start_time_str': start_time_str,
                    'station_time': station_time
                }

                m, arrival_times = optimizer.create_route_map(
                    locations, route_points, location_names,
                    time_matrix, station_time, start_time_str
                )
                st.session_state.map_data = {
                    'm': m,
                    'arrival_times': arrival_times
                }

    if st.session_state.results is not None:
        results = st.session_state.results
        
        st.success("✅ مسیر بهینه محاسبه شد!")
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📏 ماتریس فاصله (متر)")
            df_distance = pd.DataFrame(
                results['distance_matrix'],
                index=results['location_names'],
                columns=results['location_names']
            )
            st.dataframe(df_distance, key="distance_matrix_df")
        
        with col2:
            st.subheader("⏱️ ماتریس زمان (ثانیه)")
            df_time = pd.DataFrame(
                results['time_matrix'],
                index=results['location_names'],
                columns=results['location_names']
            )
            st.dataframe(df_time, key="time_matrix_df")

        end_time = datetime.strptime(results['start_time_str'], "%H:%M") + timedelta(seconds=int(results['total_time']))
        st.markdown(f"""
        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 10px; margin: 20px 0; border: 1px solid #dee2e6;">
            <h3 style="color: #1565c0; margin-bottom: 15px; text-align: right;">📊 اطلاعات کلی تور</h3>
            <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px;">
                <div style="background-color: #ffffff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e9ecef;">
                    <h4 style="color: #2196f3; margin-bottom: 10px; text-align: right;">⏱️ زمان‌بندی</h4>
                    <p style="color: #424242; margin: 5px 0; text-align: right;">
                        <strong>زمان شروع:</strong> {results['start_time_str']}
                    </p>
                    <p style="color: #424242; margin: 5px 0; text-align: right;">
                        <strong>زمان پایان:</strong> {end_time.strftime('%H:%M')}
                    </p>
                    <p style="color: #424242; margin: 5px 0; text-align: right;">
                        <strong>مدت کل:</strong> {results['total_time']/3600:.1f} ساعت
                    </p>
                </div>
                <div style="background-color: #ffffff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e9ecef;">
                    <h4 style="color: #2196f3; margin-bottom: 10px; text-align: right;">📏 مسافت و توقف‌ها</h4>
                    <p style="color: #424242; margin: 5px 0; text-align: right;">
                        <strong>مسافت کل:</strong> {results['total_distance']/1000:.1f} کیلومتر
                    </p>
                    <p style="color: #424242; margin: 5px 0; text-align: right;">
                        <strong>تعداد توقف‌ها:</strong> {len(results['location_names'])-1}
                    </p>
                    <p style="color: #424242; margin: 5px 0; text-align: right;">
                        <strong>زمان هر توقف:</strong> {results['station_time']//60} دقیقه
                    </p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if st.session_state.map_data is not None:
            st.subheader("🗺️ نقشه مسیر")
            st_folium(st.session_state.map_data['m'], width=1000, height=600)

            st.subheader("📋 جدول مسیر")
            route_data = []
            current_time = datetime.strptime(results['start_time_str'], "%H:%M")
            
            time_matrix = results['time_matrix']
            distance_matrix = results['distance_matrix']
            
            for i, point_idx in enumerate(results['route_points']):
                next_travel_time = 0
                if i < len(results['route_points']) - 1:
                    next_point_idx = results['route_points'][i + 1]
                    next_travel_time = int(time_matrix[point_idx][next_point_idx])  # تبدیل به int

                station_type = 'نقطه شروع' if i == 0 else ('نقطه پایان' if i == len(results['route_points'])-1 else 'نمایندگی')
                
                departure_time = current_time
                if i > 0 and i < len(results['route_points']) - 1:  # برای همه ایستگاه‌ها به جز نقطه شروع و پایان
                    departure_time = current_time + timedelta(seconds=int(results['station_time']))

                route_data.append({
                    'ردیف': i + 1,
                    'نام مکان': results['location_names'][point_idx],
                    'نوع': station_type,
                    'زمان رسیدن': current_time.strftime("%H:%M"),
                    'مدت توقف': f"{int(results['station_time'])//60} دقیقه" if i > 0 and i < len(results['route_points'])-1 else "-",
                    'زمان حرکت': departure_time.strftime("%H:%M") if i < len(results['route_points'])-1 else "-",
                    'زمان سفر تا ایستگاه بعدی': f"{next_travel_time//60:.0f} دقیقه" if next_travel_time > 0 else "-",
                    'مسافت تا ایستگاه بعدی': f"{float(distance_matrix[point_idx][results['route_points'][i+1]])/1000:.1f} کیلومتر" if i < len(results['route_points'])-1 else "-"
                })
                
                if i < len(results['route_points']) - 1:
                    if i > 0:  
                        current_time += timedelta(seconds=int(results['station_time']))
                    current_time += timedelta(seconds=int(next_travel_time))
            
            route_df = pd.DataFrame(route_data)
            st.dataframe(route_df, use_container_width=True, key="route_table")

if __name__ == "__main__":
    main()
