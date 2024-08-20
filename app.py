from shiny import App, render, ui, reactive
import geopandas as gpd
import folium
from folium import GeoJson, LayerControl
from branca.colormap import LinearColormap
import io
import zipfile
import tempfile
import os
import shutil
import traceback
from shapely.geometry import shape
from shapely.validation import explain_validity

app_ui = ui.page_fluid(
    ui.input_file("shapefile", "Upload Shapefile (as .zip or individual files)", 
                  accept=[".zip", ".shp", ".shx", ".dbf", ".prj"], 
                  multiple=True),
    ui.output_ui("attribute_selector"),
    ui.output_ui("map_output"),
    ui.output_text("file_info"),
    ui.output_text("debug_info"),
    ui.output_text("geometry_info")
)

def server(input, output, session):
    gdf_store = reactive.Value(None)

    @reactive.Calc
    def load_shapefile():
        files = input.shapefile()
        if not files:
            return None, "No files uploaded"

        try:
            with tempfile.TemporaryDirectory() as tmpdirname:
                if len(files) == 1 and files[0]["name"].endswith('.zip'):
                    with zipfile.ZipFile(files[0]["datapath"], 'r') as zip_ref:
                        zip_ref.extractall(tmpdirname)
                else:
                    for file in files:
                        shutil.copy(file["datapath"], os.path.join(tmpdirname, file["name"]))

                shp_file = next((os.path.join(tmpdirname, f) for f in os.listdir(tmpdirname) if f.endswith('.shp')), None)

                if shp_file:
                    gdf = gpd.read_file(shp_file)
                    
                    # Attempt to fix invalid geometries
                    gdf['geometry'] = gdf['geometry'].buffer(0)
                    
                    # Check for any remaining invalid geometries
                    invalid_geoms = gdf[~gdf.is_valid]
                    if not invalid_geoms.empty:
                        invalid_info = invalid_geoms.apply(lambda row: explain_validity(row.geometry), axis=1)
                        return gdf, f"Shapefile loaded with {len(invalid_geoms)} invalid geometries: {invalid_info.to_dict()}"
                    
                    gdf_store.set(gdf)
                    return gdf, f"Shapefile loaded successfully and all geometries are valid: {shp_file}"
                else:
                    return None, "No .shp file found in the uploaded files"

        except Exception as e:
            return None, f"Error loading shapefile: {str(e)}\n{traceback.format_exc()}"

    @output
    @render.ui
    def attribute_selector():
        gdf, _ = load_shapefile()
        if gdf is not None:
            numeric_columns = gdf.select_dtypes(include=['int64', 'float64']).columns.tolist()
            return ui.input_select("legend_attribute", "Select attribute for legend", numeric_columns)
        return ui.p("Upload a shapefile to select an attribute for the legend.")

    @output
    @render.ui
    def map_output():
        gdf = gdf_store.get()
        if gdf is not None:
            try:
                # Get the selected attribute for the legend
                legend_attr = input.legend_attribute()
                
                # Create a map centered on the mean coordinates of the shapefile
                center_lat = gdf.geometry.centroid.y.mean()
                center_lon = gdf.geometry.centroid.x.mean()
                m = folium.Map(location=[center_lat, center_lon], zoom_start=10, 
                               tiles='OpenStreetMap')
                
                # Create a color map
                min_value = gdf[legend_attr].min()
                max_value = gdf[legend_attr].max()
                colormap = LinearColormap(colors=['yellow', 'orange', 'red'], vmin=min_value, vmax=max_value)
                
                # Add the shapefile as a GeoJSON layer with colors based on the selected attribute
                GeoJson(
                    gdf,
                    style_function=lambda feature: {
                        'fillColor': colormap(feature['properties'][legend_attr]),
                        'color': 'black',
                        'weight': 1,
                        'fillOpacity': 0.7,
                    },
                    tooltip=folium.GeoJsonTooltip(fields=[legend_attr], aliases=[legend_attr])
                ).add_to(m)
                
                # Add the colormap to the map
                colormap.add_to(m)
                colormap.caption = legend_attr
                
                # Fit the map bounds to the shapefile extent
                m.fit_bounds(m.get_bounds())
                
                # Add layer control
                LayerControl().add_to(m)
                
                # Convert the map to HTML
                map_html = m._repr_html_()
                
                return ui.HTML(map_html)
            except Exception as e:
                return ui.p(f"Error creating map: {str(e)}\n{traceback.format_exc()}")
        return ui.p("Upload a zipped shapefile or individual shapefile components to view the map.")

    @output
    @render.text
    def file_info():
        gdf, debug_msg = load_shapefile()
        if gdf is not None:
            return f"Shapefile loaded: {len(gdf)} features"
        return "No valid shapefile uploaded yet. Please upload a .zip file or all necessary shapefile components (.shp, .shx, .dbf, etc.)."

    @output
    @render.text
    def debug_info():
        gdf, debug_msg = load_shapefile()
        return debug_msg

    @output
    @render.text
    def geometry_info():
        gdf, _ = load_shapefile()
        if gdf is not None:
            bounds = gdf.total_bounds
            return f"Geometry bounds: {bounds}\nCRS: {gdf.crs}\nGeometry types: {gdf.geom_type.value_counts().to_dict()}"
        return "No geometry information available."

app = App(app_ui, server)