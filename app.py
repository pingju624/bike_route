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
import streamlit as st
import io
import plotly.io as pio


filter_grade_parameter = 30

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
st.title("坡度圖、路線分析工具")

st.markdown("Tips: 可以使用google我的地圖規劃好路徑後，下載kml檔匯出，在這邊上傳")

# **KML 檔案上傳**
uploaded_file = st.file_uploader("請上傳 KML 檔案", type=["kml"])
if uploaded_file:
    # 解析 KML
    file_name = uploaded_file.name.replace(".kml", "")
    route_df, placemark_df = parse_kml(uploaded_file)

    # **讓使用者修改標記點名稱**
    st.subheader("🏷️ 修改標記點名稱")
    new_names = []
    for i in range(len(placemark_df)):
        new_name = st.text_input(f"{placemark_df.loc[i, 'name']} 的新名稱", value=placemark_df.loc[i, "name"])
        new_names.append(new_name)
    placemark_df["name"] = new_names  # 更新標記點名稱

    # **補充海拔數據**
    elevation_data = srtm.get_data()
    route_df["elevation"] = route_df.apply(lambda row: elevation_data.get_elevation(row["lat"], row["lon"]), axis=1)
    placemark_df["elevation"] = placemark_df.apply(lambda row: elevation_data.get_elevation(row["lat"], row["lon"]), axis=1)

    # **平滑海拔高度（使用高斯濾波）**
    route_df["smoothed_elevation"] = route_df["elevation"].rolling(window=30, center=True, min_periods=1).mean()
    route_df["filtered_elevation"] = gaussian_filter1d(route_df["elevation"], sigma=20)

    # **計算距離**
    route_df["distance_km"] = [0] + [geodesic((route_df.iloc[i-1]["lat"], route_df.iloc[i-1]["lon"]), 
                                              (route_df.iloc[i]["lat"], route_df.iloc[i]["lon"])).km for i in range(1, len(route_df))]
    route_df["cumulative_distance"] = route_df["distance_km"].cumsum()

    # **計算坡度**
    route_df["grade"] = route_df["filtered_elevation"].diff() / (route_df["distance_km"] * 1000) * 100
    route_df["grade"].fillna(0, inplace=True)

    # **平滑坡度數據**
    route_df["filtered_grade"] = gaussian_filter1d(route_df["grade"], sigma=30)
    route_df["smoothed_grade"] = route_df["filtered_grade"].rolling(window=100, center=True, min_periods=1).mean()

   
    # **修正標記點的位置**
    placemark_df["cumulative_distance"] = placemark_df.apply(
        lambda row: route_df.loc[((route_df["lat"] - row["lat"])**2 + (route_df["lon"] - row["lon"])**2).idxmin(), "cumulative_distance"], 
        axis=1
    )
    placemark_df["cumulative_distance"].fillna(0, inplace=True)

    # **計算統計數據**
    total_distance = route_df["cumulative_distance"].max()
    total_ascent = route_df["filtered_elevation"].diff().clip(lower=0).sum()
    total_descent = -route_df["filtered_elevation"].diff().clip(upper=0).sum()
    max_grade = route_df["smoothed_grade"].quantile(0.98)
    avg_grade = route_df["smoothed_grade"].mean()

    
    # **用戶開關**
    st.markdown("Tips: 可以點選圖例上的線來取消顯示標記點或是坡度喔！")
    show_legend = st.checkbox("顯示圖例 (Legend)", value=True)
    show_annotation = st.checkbox("顯示統計數據 (Annotation)", value=True)
    
    # **繪製爬升與坡度圖**
    fig = go.Figure()
    
    # **條件顯示統計數據**
    if show_annotation:
        fig.add_annotation(
            x=0, y=1,
            xref="paper", yref="paper",
            text=f"總距離: {total_distance:.2f} km<br>總爬升: {total_ascent:.0f} m<br>總下降: {total_descent:.0f} m<br>最大坡度: {max_grade:.1f} %<br>平均坡度: {avg_grade:.1f} %",
            showarrow=False,
            align="right",
            font=dict(size=14),
            xanchor="left",
            yanchor="top",
            xshift=0,
            yshift=20
        )
    
    # **海拔高度曲線（綠色區域）**
    fig.add_trace(go.Scatter(
        x=route_df["cumulative_distance"],
        y=route_df["filtered_elevation"],  
        mode="lines",
        name="海拔高度" if show_legend else "",  # **依據開關顯示名稱**
        line=dict(color='rgba(68, 106, 55, 1)'),
        fill='tozeroy',
        fillcolor='rgba(68, 106, 55, 0.3)',
        customdata=np.stack((route_df["cumulative_distance"], route_df["smoothed_grade"]), axis=-1),  
        hovertemplate="距離: %{customdata[0]:.2f} km<br>海拔: %{y:.2f} m<br>坡度: %{customdata[1]:.1f} %",
        yaxis="y"
    ))
    
    # # **坡度曲線（灰色虛線）**
    # fig.add_trace(go.Scatter(
    #     x=route_df["cumulative_distance"],
    #     y=route_df["smoothed_grade"],
    #     mode="lines",
    #     name="坡度 (%)" if show_legend else "",
    #     line=dict(color="gray", dash="dash"),
    #     hoverinfo="none",
    #     yaxis="y2"
    # ))
    
    # **標記點**
    for _, row in placemark_df.iterrows():
        fig.add_trace(go.Scatter(
            x=[row["cumulative_distance"]],
            y=[row["elevation"]],
            mode="markers+text",
            text=row["name"],
            textposition="top center",
            marker=dict(size=10, color="rgba(128, 0, 0, 1)"),
            name=row["name"] if show_legend else ""  # **根據選擇決定是否顯示標記點圖例**
        ))
    
    # **設定雙 Y 軸（海拔 + 坡度）**
    fig.update_layout(
        title=f" {file_name} - 高度圖",
        xaxis_title="累積距離 (km)",
        yaxis=dict(title="海拔 (m)", side="left"),
        # yaxis2=dict(title="坡度 (%)", overlaying="y", side="right"),
        hovermode="x",
        
        # **依據開關顯示圖例**
        showlegend=show_legend,
        legend=dict(
            x=1,  # 靠左
            y=1,  # 靠上
            xanchor="left",
            yanchor="top"
        ) if show_legend else None  # **如果關閉圖例，則設定為 None**
    )
    
    # **顯示圖表**
    st.plotly_chart(fig)


    m = folium.Map(location=[route_df["lat"].mean(), route_df["lon"].mean()], zoom_start=12)
    folium.PolyLine(list(zip(route_df["lat"], route_df["lon"])), color="blue", weight=2.5, opacity=1).add_to(m)

    # **標記停靠點**
    for _, row in placemark_df.iterrows():
        popup_text = f"""
        <div style="width: 200px;">
            <b>{row['name']}</b>
            - {row['cumulative_distance']:.2f} km<br>
            海拔: {row['elevation']} m
        </div>
        """
        folium.Marker(
            location=[row["lat"], row["lon"]],
            popup=folium.Popup(popup_text, max_width=100),  # **調整最大寬度**
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)

        # **固定地標名稱**
        folium.Marker(
            location=[row["lat"], row["lon"]],
            icon=folium.DivIcon(html=f"""
                <div style="font-size: 8px; font-weight: bold; color: black; text-align: center; width: 100px;">
                    {row['name']}
                </div>
            """),
        ).add_to(m)


    folium_static(m)

