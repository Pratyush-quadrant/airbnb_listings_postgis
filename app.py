import streamlit as st
import folium
from streamlit_folium import st_folium
from sqlalchemy import text
import geopandas as gpd
import pandas as pd
from db_utils import get_engine

st.set_page_config(layout="wide")
st.title("NYC AirBnB Finder by Neighborhood, Price & Subway Proximity")
st.markdown(
    "Filter AirBnBs by neighborhood, price category, and optionally show only listings within 400m of a subway."
)

engine = get_engine()

@st.cache_data(ttl=3600)
def load_neighborhoods():
    sql = "SELECT DISTINCT name FROM nyc_neighborhoods ORDER BY name"
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    return df['name'].tolist()

@st.cache_data(ttl=3600)
def get_price_categories():
    sql = "SELECT price::numeric AS price FROM nyc_listings_bnb WHERE price IS NOT NULL"
    with engine.connect() as conn:
        prices = pd.read_sql(sql, conn)['price']
    q1 = int(prices.quantile(0.25))
    q2 = int(prices.quantile(0.5))
    q3 = int(prices.quantile(0.75))
    max_p = int(prices.max())
    categories = [
        ("Below $" + str(q1), (0, q1)),
        (f"${q1} to ${q2}", (q1, q2)),
        (f"${q2} to ${q3}", (q2, q3)),
        (f"Above ${q3}", (q3, max_p + 1)),
    ]
    return categories

def fetch_listings(neighborhood, price_range, near_subway):
    sql = """
    SELECT
        bnb.id,
        bnb.name,
        bnb.price::numeric AS price,
        bnb.room_type,
        bnb.latitude,
        bnb.longitude,
        bnb.listing_geom
    FROM nyc_listings_bnb bnb
    JOIN nyc_neighborhoods nh ON ST_Contains(nh.geom, ST_Transform(bnb.listing_geom, ST_SRID(nh.geom)))
    WHERE nh.name = :neighborhood
      AND bnb.price::numeric >= :price_min
      AND bnb.price::numeric < :price_max
    """

    params = {
        "neighborhood": neighborhood,
        "price_min": price_range[0],
        "price_max": price_range[1],
    }

    if near_subway:
        sql += """
        AND EXISTS (
            SELECT 1 FROM nyc_subway_stations ss
            WHERE ST_DWithin(
                ST_Transform(bnb.listing_geom, 4326),
                ST_Transform(ss.geom, 4326),
                400
            )
        )
        """

    with engine.connect() as conn:
        gdf = gpd.read_postgis(text(sql), conn, params=params, geom_col='listing_geom')
    return gdf


# Sidebar filters
st.sidebar.header("Filters")

neighborhoods = load_neighborhoods()
selected_neighborhood = st.sidebar.selectbox("Select Neighborhood", [""] + neighborhoods)

price_categories = get_price_categories()
price_labels = [cat[0] for cat in price_categories]
selected_price_label = st.sidebar.selectbox("Select Price Range", price_labels)
price_range = price_categories[price_labels.index(selected_price_label)][1]

near_subway = st.sidebar.checkbox("Only show listings within 400 meters of a subway station")

if "search_clicked" not in st.session_state:
    st.session_state.search_clicked = False

def do_search():
    if selected_neighborhood:
        st.session_state.search_clicked = True
    else:
        st.warning("Please select a neighborhood to search.")

st.sidebar.button("Search Listings", on_click=do_search)

if st.session_state.search_clicked:
    listings = fetch_listings(selected_neighborhood, price_range, near_subway)
    st.subheader(f"Found {len(listings)} Listings in {selected_neighborhood}")

    if listings.empty:
        st.warning("No listings found with selected filters.")
    else:
        center_lat = listings.iloc[0].latitude
        center_lon = listings.iloc[0].longitude
        m = folium.Map(location=[center_lat, center_lon], zoom_start=14)

        for _, row in listings.iterrows():
            folium.Marker(
                [row.latitude, row.longitude],
                popup=f"{row.name}<br>Room: {row.room_type}<br>Price: ${int(row.price)}",
                icon=folium.Icon(color="blue", icon="home"),
            ).add_to(m)

        st_folium(m, width=1000, key="map")

else:
    st.info("Please select filters and click 'Search Listings'.")
