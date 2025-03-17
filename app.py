import streamlit as st
import xml.etree.ElementTree as ET
import pandas as pd
import srtm
import folium
import plotly.graph_objects as go
from geopy.distance import geodesic
from streamlit_folium import folium_static
import numpy as np
from scipy.ndimage import gaussian_filter1d

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

    # **濾波海拔數據**
    route_df["filtered_elevation"] = gaussian_filter1d(route_df["elevation"], sigma=5)

    # **計算距離**
    route_df["distance_km"] = [0] + [geodesic((route_df.iloc[i-1]["lat"], route_df.iloc[i-1]["lon"]), 
                                              (route_df.iloc[i]["lat"], route_df.iloc[i]["lon"])).km for i in range(1, len(route_df))]
    route_df["cumulative_distance"] = route_df["distance_km"].cumsum()

    # **重新計算坡度**
    route_df["filtered_grade"] = route_df["filtered_elevation"].diff() / (route_df["distance_km"] * 1000) * 100
    route_df["filtered_grade"] = route_df["filtered_grade"].rolling(window=50, center=True, min_periods=1).mean()

    # **計算統計數據**
    total_distance = route_df["cumulative_distance"].max()
    total_ascent = route_df["filtered_elevation"].diff().clip(lower=0).sum()
    total_descent = -route_df["filtered_elevation"].diff().clip(upper=0).sum()
    max_grade = route_df["filtered_grade"].max()
    avg_grade = route_df["filtered_grade"].mean()

    # **繪製爬升與坡度圖**
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=route_df["cumulative_distance"],
        y=route_df["filtered_elevation"],  
        mode="lines",
        name="海拔高度 (m)",
        line=dict(color="blue")
    ))

    fig.add_trace(go.Scatter(
        x=route_df["cumulative_distance"],
        y=route_df["filtered_grade"],
        mode="lines",
        name="坡度 (%)",
        line=dict(color="red", dash="dot"),
        yaxis="y2"
    ))

    st.plotly_chart(fig)

    # **生成互動地圖**
    m = folium.Map(location=[route_df["lat"].mean(), route_df["lon"].mean()], zoom_start=12)
    folium.PolyLine(list(zip(route_df["lat"], route_df["lon"])), color="blue", weight=2.5, opacity=1).add_to(m)

    folium_static(m)
