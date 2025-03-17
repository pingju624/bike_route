import streamlit as st
import xml.etree.ElementTree as ET
import pandas as pd
import srtm
import folium
import plotly.graph_objects as go
from geopy.distance import geodesic
from streamlit_folium import folium_static
import numpy as np

# **函數：解析 KML 檔案**
def parse_kml(file):
    namespace = {"kml": "http://www.opengis.net/kml/2.2"}
    tree = ET.parse(file)
    root = tree.getroot()

    # **解析路線 (LineString)**
    route_data = []
    route = root.find(".//kml:LineString/kml:coordinates", namespace)
    if route is not None:
        coord_list = route.text.strip().split(" ")
        for coord in coord_list:
            parts = coord.split(",")
            if len(parts) >= 2:
                try:
                    lon, lat = map(float, parts[:2])
                    route_data.append([lat, lon])
                except ValueError:
                    continue
    route_df = pd.DataFrame(route_data, columns=["lat", "lon"])

    # **解析標記點 (Placemark)**
    placemark_data = []
    placemarks = root.findall(".//kml:Placemark", namespace)
    for placemark in placemarks:
        name = placemark.find("kml:name", namespace)
        point = placemark.find(".//kml:Point/kml:coordinates", namespace)
        if name is not None and point is not None:
            parts = point.text.strip().split(",")
            if len(parts) >= 2:
                try:
                    lon, lat = map(float, parts[:2])
                    placemark_data.append([lat, lon, name.text])
                except ValueError:
                    continue
    placemark_df = pd.DataFrame(placemark_data, columns=["lat", "lon", "name"])

    return route_df, placemark_df

# **坡度計算函數**
def calculate_smoothed_grade(route_df, min_distance=0.5):  # 0.02 km = 20m
    grades = []
    for i in range(len(route_df)):
        # 找到前後相距至少 min_distance km 的最近點
        forward_idx = next((j for j in range(i + 1, len(route_df)) if route_df.loc[j, "cumulative_distance"] - route_df.loc[i, "cumulative_distance"] >= min_distance), None)
        backward_idx = next((j for j in range(i - 1, -1, -1) if route_df.loc[i, "cumulative_distance"] - route_df.loc[j, "cumulative_distance"] >= min_distance), None)

        if forward_idx is not None and backward_idx is not None:
            # 使用這兩個點來計算坡度
            elev_diff = route_df.loc[forward_idx, "elevation"] - route_df.loc[backward_idx, "elevation"]
            dist_diff = route_df.loc[forward_idx, "cumulative_distance"] - route_df.loc[backward_idx, "cumulative_distance"]
            grade = (elev_diff / (dist_diff * 1000)) * 100  # 坡度（%）
        else:
            grade = np.nan  # 若無法計算則設為 NaN
        
        grades.append(grade)

    return pd.Series(grades)

# **Streamlit UI**
st.title("🚴‍♂️ 自行車路線分析工具")

# **KML 檔案上傳**
uploaded_file = st.file_uploader("請上傳 KML 檔案", type=["kml"])
if uploaded_file:
    # 解析 KML
    route_df, placemark_df = parse_kml(uploaded_file)

    # **補充海拔數據**
    elevation_data = srtm.get_data()
    route_df["elevation"] = route_df.apply(lambda row: elevation_data.get_elevation(row["lat"], row["lon"]), axis=1)
    placemark_df["elevation"] = placemark_df.apply(lambda row: elevation_data.get_elevation(row["lat"], row["lon"]), axis=1)

    # **計算距離**
    route_df["distance_km"] = [0] + [geodesic((route_df.iloc[i-1]["lat"], route_df.iloc[i-1]["lon"]), 
                                              (route_df.iloc[i]["lat"], route_df.iloc[i]["lon"])).km for i in range(1, len(route_df))]
    route_df["cumulative_distance"] = route_df["distance_km"].cumsum()

    # **計算坡度（使用前後20m方法）**
    route_df["smoothed_grade"] = calculate_smoothed_grade(route_df)

    # **修正標記點的位置**
    placemark_df["cumulative_distance"] = placemark_df.apply(
        lambda row: route_df.loc[((route_df["lat"] - row["lat"])**2 + (route_df["lon"] - row["lon"])**2).idxmin(), "cumulative_distance"], 
        axis=1
    )

    # **計算統計數據**
    total_distance = route_df["cumulative_distance"].max()
    total_ascent = route_df["elevation"].diff().clip(lower=0).sum()
    total_descent = -route_df["elevation"].diff().clip(upper=0).sum()
    max_grade = route_df["smoothed_grade"].max()
    avg_grade = route_df["smoothed_grade"].mean()

    # **繪製爬升與坡度圖**
    fig = go.Figure()

    # **顯示統計數據**
    fig.add_annotation(
        x=0, y=1.05,
        xref="paper", yref="paper",
        text=f"總距離: {total_distance:.2f} km<br>總爬升: {total_ascent:.0f} m<br>總下降: {total_descent:.0f} m<br>最大坡度: {max_grade:.1f} %<br>平均坡度: {avg_grade:.1f} %",
        showarrow=False,
        align="left",
        font=dict(size=14)
    )

    fig.add_trace(go.Scatter(
        x=route_df["cumulative_distance"],
        y=route_df["elevation"],
        mode="lines",
        name="海拔高度 (m)",
        line=dict(color="blue")
    ))

    fig.add_trace(go.Scatter(
        x=route_df["cumulative_distance"],
        y=route_df["smoothed_grade"],
        mode="lines",
        name="坡度 (%)",
        line=dict(color="red", dash="dot"),
        yaxis="y2"
    ))

    fig.update_layout(
        title="🚴‍♂️ 爬升與坡度圖",
        xaxis_title="累積距離 (km)",
        yaxis=dict(title="海拔 (m)"),
        yaxis2=dict(title="坡度 (%)", overlaying="y", side="right"),
        hovermode="x"
    )

    st.plotly_chart(fig)

    # **生成互動地圖**
    st.subheader("🗺️ 互動式地圖")
    m = folium.Map(location=[route_df["lat"].mean(), route_df["lon"].mean()], zoom_start=12)
    folium.PolyLine(list(zip(route_df["lat"], route_df["lon"])), color="blue", weight=2.5, opacity=1).add_to(m)

    # **標記停靠點**
    for _, row in placemark_df.iterrows():
        folium.Marker(
            location=[row["lat"], row["lon"]],
            popup=f"{row['name']} - {row['cumulative_distance']:.2f} km\n海拔: {row['elevation']} m",
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)

    folium_static(m)
