import streamlit as st
import xml.etree.ElementTree as ET
import pandas as pd
import srtm
import folium
import plotly.graph_objects as go
from geopy.distance import geodesic
from streamlit_folium import folium_static

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

    # **讓使用者修改標記點名稱**
    st.subheader("🏷️ 修改標記點名稱")
    for i in range(len(placemark_df)):
        new_name = st.text_input(f"{placemark_df.loc[i, 'name']} 的新名稱", value=placemark_df.loc[i, "name"])
        placemark_df.loc[i, "name"] = new_name  # 更新名稱

    # **補充海拔數據**
    st.subheader("📊 生成爬升與坡度圖")
    elevation_data = srtm.get_data()
    route_df["elevation"] = route_df.apply(lambda row: elevation_data.get_elevation(row["lat"], row["lon"]), axis=1)
    placemark_df["elevation"] = placemark_df.apply(lambda row: elevation_data.get_elevation(row["lat"], row["lon"]), axis=1)

    # **計算坡度與累積距離**
    route_df["distance_km"] = [0] + [geodesic((route_df.iloc[i-1]["lat"], route_df.iloc[i-1]["lon"]), 
                                              (route_df.iloc[i]["lat"], route_df.iloc[i]["lon"])).km for i in range(1, len(route_df))]
    route_df["cumulative_distance"] = route_df["distance_km"].cumsum()
    route_df["grade"] = route_df["elevation"].diff() / (route_df["distance_km"] * 1000) * 100
    route_df["grade"].fillna(0, inplace=True)

    # **平滑坡度數據（移動平均）**
    route_df["smoothed_grade"] = route_df["grade"].rolling(window=100, center=True, min_periods=1).mean()

    # **修正標記點的位置**
    placemark_df["cumulative_distance"] = placemark_df.apply(
        lambda row: route_df.loc[((route_df["lat"] - row["lat"])**2 + (route_df["lon"] - row["lon"])**2).idxmin(), "cumulative_distance"], 
        axis=1
    )

    # **繪製爬升與坡度圖**
    fig = go.Figure()

    # **海拔曲線**
    fig.add_trace(go.Scatter(
        x=route_df["cumulative_distance"],
        y=route_df["elevation"],
        mode="lines",
        name="海拔高度 (m)",
        line=dict(color="blue"),
        customdata=route_df["smoothed_grade"],  # 加入坡度資訊
        hovertemplate="距離: %{x:.2f} km<br>海拔: %{y:.2f} m<br>坡度: %{customdata:.1f} %"
    ))

    # **坡度曲線（平滑後）**
    fig.add_trace(go.Scatter(
        x=route_df["cumulative_distance"],
        y=route_df["smoothed_grade"],
        mode="lines",
        name="坡度 (%)",
        line=dict(color="red", dash="dot"),  # 紅色虛線
        yaxis="y2"
    ))

    # **標記點**
    for _, row in placemark_df.iterrows():
        fig.add_trace(go.Scatter(
            x=[row["cumulative_distance"]],
            y=[row["elevation"]],
            mode="markers+text",
            text=row["name"],
            textposition="top center",
            marker=dict(size=10, color="red"),
            name=row["name"]
        ))

    # **設定雙 Y 軸（海拔 + 坡度）**
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

    # **標記點（只顯示停留點）**
    for _, row in placemark_df.iterrows():
        folium.Marker(
            location=[row["lat"], row["lon"]],
            popup=f"{row['name']}\n海拔: {row['elevation']} m",
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)

    folium_static(m)  # 顯示地圖
