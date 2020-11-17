import os
import time
import argparse
import geojson
import json
import shapefile
import shapely.wkt
from shapely.geometry import shape
from shapely.geometry import Polygon
from pykml import parser
from osgeo import ogr
from osgeo import gdal


def arguments():
    parser = argparse.ArgumentParser(description='LAS/LAZ -> GTiff Converter')
    parser.add_argument('input_filename')
    parser.add_argument('output_filename')
    parser.add_argument('--resolution', type=float, default=1,
                        help = "Set the resolution of the output GTiff")
    parser.add_argument('--clip', type=str,
                        help = "--clip <file_path>, clip output to a SHP/KML/GeoJSON")
    parser.add_argument('--hwm', type=str,
                        help = "--hwm <high_water_mark_polygon_file>, clip output to a SHP/KML/GeoJSON")
    parser.add_argument('--dtm', type=int, default=0,
                        help="--dtm <1> to output a DTM")
    parser.add_argument('--dsm', type=int, default=0,
                        help="--dsm <1> to output a DSM")
    parser.add_argument('--count', type=int, default=0,
                        help="--count <1> to output a tiff containing point count for dsm/dtm, requires a dtm/dsm output")
    parser.add_argument('--contour', type=int, default=0,
                        help="--contour <1> to output a contour line shapefile, requires DTM output")
    parser.add_argument('--color', type=int, default=0,
                        help="--color <1> to output a colored hillshade from DTM/DSM, requires either a DTM/DSM Output")
    parser.add_argument('--points', type =int, default=0,
                        help = "--points <1> to output a new las file that has been clipped")
    parser.add_argument('--in_epsg', type =str, default="2157",
                        help = "--InEPSG <EPSG Code>, if left blank input EPSG is assumed to be 2157")
    parser.add_argument('--out_epsg', type =str, default="2157",
                        help = "--OutEPSG <EPSG Code>, if left blank output EPSG is defaults to 2157")
    parser.add_argument('--classify', type =bool, default=False,
                        help = "set as True for unclassified point clouds, default False")
    parser.add_argument('--clean', type =bool, default=False,
                        help = "Set as True to remove noise, default False")

    return parser.parse_args()

def loadGeoJson(file):
    if file.split('.')[1] == "geojson":
        with open(file) as map:
            g1 = geojson.load(map)
        g1 = g1["features"][0]["geometry"]
        geom = shape(g1)
        geomWkt = geom.wkt
        return geomWkt

def loadShapeFile(file):
    if file.split('.')[1] == "geojson":
        with open(file) as map:
            g1 = geojson.load(map)
        geom = shape(g1)
        geomWkt = geom.wkt
        os.remove("scratch.geojson")
        return geomWkt

    elif file.split('.')[1] == "shp":
        shapef= shapefile.Reader(file)
        feature = shapef.shapeRecords()[0]
        first = feature.shape.__geo_interface__
        with open ('scratch.geojson', 'w') as outfile:
            json.dump(first, outfile)
        return loadShapeFile("scratch.geojson")

def loadKml(file):
    data = parser.parse(file).getroot()
    coords = data.Document.Folder.Placemark.Polygon.outerBoundaryIs.LinearRing.coordinates
    string = "" + coords
    modified = string.replace(',', '~')
    modified = modified.replace(' ', ',')
    modified = modified.replace('~', ' ')
    modified = "POLYGON ((" + modified + "))"
    return modified

def wktPolygonToShapefile(polygon):
    poly = shapely.wkt.loads(polygon)
    driver = ogr.GetDriverByName("Esri Shapefile")
    ds = driver.CreateDataSource('scratch.shp')
    layer = ds.CreateLayer('', None, ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn('id', ogr.OFTInteger))
    defn = layer.GetLayerDefn()
    feat = ogr.Feature(defn)
    feat.SetField('id', 0)
    geom = ogr.CreateGeometryFromWkb(poly.wkb)
    feat.SetGeometry(geom)
    layer.CreateFeature(feat)
    feat = geom = None
    ds = layer = feat = geom = None

def buildPipeInput(in_epsg,out_epsg, filename):
    if filename.split('.')[1]=="las"or filename.split('.')[1]=="laz":
        epsg = in_epsg
        myDictObj = {"pipeline":[{"type": "readers.las", "spatialreference": "EPSG:"+epsg,
        "filename":filename},
        {"type":"filters.reprojection", "in_srs": "EPSG:"+in_epsg,
        "out_srs":"EPSG:"+out_epsg},
        ]}
        return myDictObj
    else:
        print("Error: Invalid input file")

def appendNoiseFilterToPipe(myDictObj):
    myDictObj["pipeline"].append({
    "type":"filters.outlier",
    "method":"statistical",
    "multiplier":3,
    "mean_k":8
    })
    myDictObj["pipeline"].append({
    "type":"filters.range",
    "limits": "Classification![7:7],Z[-100:3000]"
    })
    return myDictObj

def appendElmFilterToPipe(myDictObj):
    myDictObj["pipeline"].append({
    "type":"filters.elm",
    "cell":20.0,
    "class":7,
    "threshold":2
    })
    return myDictObj

def appendCropToPipe(myDictObj, cropShape, epsg):
    myDictObj["pipeline"].append({
    "type":"filters.crop",
    "a_srs":"EPSG:"+epsg,
    "polygon":cropShape
    })
    return myDictObj

def appendHWMCropToPipe(myDictObj, cropShape, epsg):
    myDictObj["pipeline"].append({
    "type":"filters.crop",
    "outside":True,
    "a_srs":"EPSG:"+epsg,
    "polygon":cropShape
    })
    return myDictObj

def appendSmrfFilterToPipe(myDictObj):
    myDictObj["pipeline"].append({
    "type":"filters.smrf",
    "ignore":"Classification[7:7]",
    "slope":0.2,
    "window":60,
    "threshold":0.95,
    "cell":7,
    "scalar":1.2,
    "slope":.3
    })
    return myDictObj

def append_hag_filter(myDictObj):
    myDictObj["pipeline"].append({
    "type":"filters.hag"
    })
    myDictObj["pipeline"].append({
    "type": "filters.range",
    "limits": "HeightAboveGround[2:)"
    })


    return myDictObj

def append_approximate_coplanar(myDictObj):
    myDictObj["pipeline"].append({
    "type":"filters.approximatecoplanar",
    "knn":10
    })

    return myDictObj

def append_neighbor_classifier(myDictObj):
    myDictObj["pipeline"].append({
    "type":"filters.neighborclassifier",
    "domain":"Classification![2:2]",
    "k":20
    })
    return myDictObj

def appendPMFtoPipe(myDictObj):
    myDictObj["pipeline"].append({
    "type":"filters.pmf",
    "max_window_size":40,
    "cell_size": 1.4,
    "exponential":True,
    "slope":1
    })
    return myDictObj

def appendGroundFilter(myDictObj):
    myDictObj["pipeline"].append({
    "type":"filters.range",
    "limits":"Classification[2:2]"
    })
    return myDictObj

def appendGtiffWriterToPipe(myDictObj, output_type, output_filename, output_resolution):
    myDictObj["pipeline"].append({
    "type":"writers.gdal",
    "filename": output_filename,
    "resolution":output_resolution,
    "output_type":output_type
    })
    return myDictObj

def append_las_writer(myDictObj, output_filename):
    myDictObj["pipeline"].append({
    "type":"writers.las",
    "filename": output_filename,
    })
    return myDictObj

def getPolygon(clip):
    #Parse clipping file into WKT format
    clippingMask=""
    if clip.split('.')[1] == "shp":
        clippingMask = loadShapeFile(clip)
    elif clip.split('.')[1] == "kml":
        clippingMask = loadKml(clip)
    elif clip.split('.')[1] == "geojson":
        clippingMask = loadGeoJson(clip)
    else:
        #If Unsupported file type print error
        print("Unsupported Clipping Filetype")
        return False
    return clippingMask

def interpolate(file, ext):
    out = args.output_filename+ext+"tif"
    if args.clip is not None:
        wktPolygonToShapefile(getPolygon(args.clip))
        print(out)
        os.system("saga_cmd grid_tools 7 -INPUT "+"scratch"+file + " -RESULT scratch")
        os.system("saga_cmd grid_tools 31 -GRIDS scratch.sgrd -POLYGONS scratch.shp -CLIPPED scratchtes6 -EXTENT 3")
        os.system("saga_cmd io_gdal 2 -GRIDS scratchtes6.sgrd -FILE "+ out)
    else:
        os.system("saga_cmd grid_tools 7 -INPUT "+"scratch"+file + " -RESULT scratch")
        os.system("saga_cmd io_gdal 2 -GRIDS scratch.sgrd -FILE "+ out)

def cleanup():
    files = os.listdir()
    for file in files:
        if (file.startswith("scratch")):
            os.remove(file)

def output_tif(ext):#_dsm. _dsm_count. _dtm. _dtm_count.
    myDictObj = buildPipeInput(args.in_epsg, args.out_epsg, args.input_filename)
    #Check for clipping file
    if args.hwm is not None:
        clippingMask = getPolygon(args.hwm)
        myDictObj = appendHWMCropToPipe(myDictObj, clippingMask, "29903")
    if args.clip is not None:
        clippingMask = getPolygon(args.clip)
        myDictObj = appendCropToPipe(myDictObj, clippingMask, args.out_epsg)

    if args.clean == 1:
        myDictObj = appendNoiseFilterToPipe(myDictObj)
        myDictObj = appendElmFilterToPipe(myDictObj)

    if args.classify == True:
        myDictObj = appendSmrfFilterToPipe(myDictObj)
        myDictObj = append_neighbor_classifier(myDictObj)

    filename=args.output_filename+ext+"tif"

    if ext == "_dtm_count." or ext == "_dtm.":
        myDictObj = appendGroundFilter(myDictObj)

    if ext == "_dsm_count." or ext == "_dtm_count.":
        myDictObj = appendGtiffWriterToPipe(myDictObj, "count", "scratch"+filename, args.resolution)
    elif ext == "_dsm.":
        myDictObj = appendGtiffWriterToPipe(myDictObj, "max", "scratch"+filename, args.resolution)
    elif ext == "_dtm.":
        myDictObj = appendGtiffWriterToPipe(myDictObj, "mean", "scratch"+filename, args.resolution)

    with open ('scratchpipeline.json', 'w') as outfile:
        json.dump(myDictObj, outfile)
    os.system("pdal pipeline scratchpipeline.json")

    interpolate(filename,ext)
    cleanup()

def output_las():
    myDictObj = buildPipeInput(args.in_epsg, args.out_epsg, args.input_filename)
    #Check for clipping file
    if args.hwm is not None:
        clippingMask = getPolygon(args.hwm)
        myDictObj = appendHWMCropToPipe(myDictObj, clippingMask, "29903")
    if args.clip is not None:
        clippingMask = getPolygon(args.clip)
        myDictObj = appendCropToPipe(myDictObj, clippingMask, args.out_epsg)
    if args.clean == 1:
        myDictObj = appendNoiseFilterToPipe(myDictObj)
        myDictObj = appendElmFilterToPipe(myDictObj)

    myDictObj = append_las_writer(myDictObj, args.output_filename + ".las")
    with open ('scratchpipeline.json', 'w') as outfile:
        json.dump(myDictObj, outfile)
    os.system("pdal pipeline scratchpipeline.json")
    cleanup()

def output_contour():
    os.system("saga_cmd shapes_grid 5 -GRID "+args.output_filename +"_dtm.tif" + " -CONTOUR scratchcontour_"+args.output_filename + " -ZSTEP 5")
    shapefile_to_geojson()

def shapefile_to_geojson():
    driver = ogr.GetDriverByName('ESRI Shapefile')
    shp_path = "scratchcontour_"+ args.output_filename +".shp"
    data_source = driver.Open(shp_path, 0)

    fc = {'type':'FeatureCollection',
    'features':[]}

    lyr=data_source.GetLayer(0)
    for feature in lyr:
        fc['features'].append(feature.ExportToJson(as_object=True))

    with open (args.output_filename+"_contour.geojson", 'w') as out:
        json.dump(fc, out)

def write_color_config(color_heights):
    file = open("scratchcolor_config.txt", "w+")
    file.write(color_heights)

def get_height_intervals_colors(input_file, color_arr):
    gtif = gdal.Open(input_file)
    srcband = gtif.GetRasterBand(1)
    stats = srcband.GetStatistics(True,True)
    mean = stats[2]
    st_dv = stats[3]
    col_loc = int(len(color_arr)/5)
    height = mean - 2*st_dv

    str_color = ""

    for x in range(5):
        col_loc = int(((len(color_arr)/5)*(x+1))-1)
        str_color += "%.3f %.3f %.3f %.3f\n" % (height, color_arr[col_loc][0],color_arr[col_loc][1],color_arr[col_loc][2])
        height+=st_dv

    return str_color

def colorize_tif(in_file):
    out_file = in_file.split('.')[0]+"_color.tif"
    os.system("gdaldem color-relief %s scratchcolor_config.txt scratchcolor.tif" % (in_file))
    os.system("composite -blend 60 scratchcolor.tif scratchhill.tif scratchcolored_hill.tif")
    os.system("listgeo %s > scratchgeodata.txt" % (in_file))
    os.system("geotifcp -g scratchgeodata.txt scratchcolored_hill.tif %s" % (out_file))

def generate_hillshade(in_file):
    os.system("gdaldem hillshade -z 11 -multidirectional %s scratchhill.tif" % (in_file))

def output_color_tif(ext):
    in_file = args.output_filename+ext+"tif"
    generate_hillshade(in_file)
    if args.dtm == 1 and args.dsm==1:
        in_file = args.output_filename + "_dtm.tif"
    colors = get_height_intervals_colors(in_file, rygbb_5)
    if ext == "_dsm." and args.dtm == 1:
        in_file = args.output_filename+ext+"tif"
    print(colors)
    ext+= "_color"
    write_color_config(colors)
    x = colorize_tif(in_file)
    cleanup()

viridis_rgb_52 = [[68,1,84],
                [70,8,92],
                [71,16,99],
                [72,23,105],
                [72,29,11],
                [72,36,117],
                [71,42,122],
                [70,48,126],
                [69,55,129],
                [67,61,132],
                [65,66,135],
                [63,72,137],
                [61,78,138],
                [58,83,139],
                [56,89,140],
                [53,94,141],
                [51,99,141],
                [49,104,142],
                [46,109,142],
                [44,113,142],
                [42,118,142],
                [41,123,142],
                [39,128,142],
                [37,132,142],
                [35,137,142],
                [33,142,141],
                [32,146,140],
                [31,151,139],
                [30,156,137],
                [31,161,136],
                [33,165,133],
                [36,170,131],
                [40,174,128],
                [46,179,124],
                [53,183,121],
                [61,188,116],
                [70,192,111],
                [80,196,106],
                [90,200,100],
                [101,203,94],
                [112,207,87],
                [124,210,80],
                [137,213,72],
                [149,216,64],
                [162,218,55],
                [176,221,47],
                [189,223,38],
                [202,225,31],
                [216,226,25],
                [229,228,25],
                [241,229,29],
                [253,231,37]]

viridis_rgb_5 = [[68,1,84],
                [58,82,139],
                [32,144,141],
                [93,201,98],
                [253,231,37]]

red_blue_5 = [[233,8,8],
            [173,16,244],
            [147,7,244],
            [39,22,227],
            [22,2,238]]

blue_green_5 = [[93,78,255],
                [82,164,255],
                [0,249,255],
                [80,255,127],
                [68,255,50]]

rygbb_5 = [[0,89,255],
                [0,255,238],
                [94,255,0],
                [255,217,0],
                [255,30,0]
                            ]
args = arguments()
if args.dtm==1 and args.count == 1:
    output_tif("_dtm.")
    output_tif("_dtm_count.")
elif args.dtm == 1:
    output_tif("_dtm.")
if args.dsm == 1 and args.count == 1:
    output_tif("_dsm.")
    output_tif("_dsm_count.")
elif args.dsm == 1:
    output_tif("_dsm.")

if args.contour==1 and args.dtm==0:
    print("Error, no dtm found to produce contour lines")
elif args.contour ==1 and args.dtm==1:
    output_contour()

if args.color == 1 and args.dtm == 1:
    output_color_tif("_dtm.")
if args.color ==1 and args.dsm == 1:
    output_color_tif("_dsm.")
if args.color == 1 and args.dsm == 0 and args.dtm ==0:
    print("Error, No DSM/DTM to produce colored dtm from")

if args.points == 1:
    output_las()

cleanup()
