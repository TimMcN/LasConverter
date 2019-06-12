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


def arguments():
    parser = argparse.ArgumentParser(description='LAS/LAZ -> GTiff Converter')
    parser.add_argument('input_filename')
    parser.add_argument('output_filename')
    parser.add_argument('--resolution', type=int, default=1,
                        help = "Set the resolution of the output GTiff")
    parser.add_argument('--clip', type=str,
                        help = "--clip <file_path>, clip output to a SHP/KML/GeoJSON")
    parser.add_argument('--dtm', type=int, default=0,
                        help="--dtm <1> to output a DTM")
    parser.add_argument('--dsm', type=int, default=0,
                        help="--dsm <1> to output a DSM")
    parser.add_argument('--contour', type=int, default=0,
                        help="--contour <1> to output a contour line shapefile")
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

def appendNoiseFilterToPipe():
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

def appendElmFilterToPipe():
    myDictObj["pipeline"].append({
    "type":"filters.elm",
    "cell":20.0,
    "class":7,
    "threshold":2
    })
    return myDictObj

def appendCropToPipe(cropShape, epsg):
    myDictObj["pipeline"].append({
    "type":"filters.crop",
    "a_srs":"EPSG:"+epsg,
    "polygon":cropShape
    })
    return myDictObj

def appendSmrfFilterToPipe():
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

def append_hag_filter():
    myDictObj["pipeline"].append({
    "type":"filters.hag"
    })
    myDictObj["pipeline"].append({
    "type": "filters.range",
    "limits": "HeightAboveGround[2:)"
    })


    return myDictObj

def append_approximate_coplanar():
    myDictObj["pipeline"].append({
    "type":"filters.approximatecoplanar",
    "knn":10
    })

    return myDictObj

def append_neighbor_classifier():
    myDictObj["pipeline"].append({
    "type":"filters.neighborclassifier",
    "domain":"Classification![2:2]",
    "k":20
    })
    return myDictObj

def appendPMFtoPipe():
    myDictObj["pipeline"].append({
    "type":"filters.pmf",
    "max_window_size":40,
    "cell_size": 1.4,
    "exponential":True,
    "slope":1
    })
    return myDictObj

def appendGroundFilter():
    myDictObj["pipeline"].append({
    "type":"filters.range",
    "limits":"Classification[2:2]"
    })
    return myDictObj

def appendGtiffWriterToPipe(dsm, outputFileName, outputResolution):
    if dsm == 1:
        myDictObj["pipeline"].append({
        "type":"writers.gdal",
        "filename": outputFileName,
        "resolution":outputResolution,
        "output_type":"mean"
        })
    else:
        myDictObj["pipeline"].append({
        "type":"writers.gdal",
        "filename": outputFileName,
        "resolution":outputResolution,
        "output_type":"min"
        })
    return myDictObj

def getPolygon():
    #Parse clipping file into WKT format
    clippingMask=""
    if args.clip.split('.')[1] == "shp":
        clippingMask = loadShapeFile(args.clip)
    elif args.clip.split('.')[1] == "kml":
        clippingMask = loadKml(args.clip)
    elif args.clip.split('.')[1] == "geojson":
        clippingMask = loadGeoJson(args.clip)
    else:
        #If Unsupported file type print error
        print("Unsupported Clipping Filetype")
        return False
    return clippingMask

def interpolate(file, ext):
    if args.clip is not None:
        wktPolygonToShapefile(getPolygon())
        out = args.output_filename.split('.')[0]+ext+args.output_filename.split('.')[1]
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

def output_dsm():
    print("output")

def output_dtm():
    print("output")

def output_contour():
    os.system("saga_cmd shapes_grid 5 -GRID "+args.output_filename.split('.')[0]+"_dtm."+ args.output_filename.split('.')[1] + " -CONTOUR contour_"+args.output_filename.split('.')[0]+"_contours")



args = arguments()

if args.dtm==1:
    myDictObj = buildPipeInput(args.in_epsg, args.out_epsg, args.input_filename)
    #Check for clipping file
    if args.clip is not None:
        #Build clipping pipe
        clippingMask = getPolygon()
        myDictObj = appendCropToPipe(clippingMask, args.out_epsg)

    if args.clean == True:
        myDictObj = appendNoiseFilterToPipe()
        myDictObj = appendElmFilterToPipe()

    if args.classify == True:
        myDictObj = appendSmrfFilterToPipe()
        myDictObj = append_neighbor_classifier()
    filename=args.output_filename.split('.')[0]+"_dtm."+args.output_filename.split('.')[1]
    print(filename)
    myDictObj = appendGroundFilter()
    myDictObj = appendGtiffWriterToPipe(0, "scratch"+filename, args.resolution)

    with open ('scratchpipeline.json', 'w') as outfile:
        json.dump(myDictObj, outfile)
    os.system("pdal pipeline scratchpipeline.json")

    interpolate(filename,"_dtm.")
    cleanup()
if args.dsm==1:
    myDictObj = buildPipeInput(args.in_epsg, args.out_epsg, args.input_filename)
    #Check for clipping file
    if args.clip is not None:
        #Build clipping pipe
        clippingMask = getPolygon()
        myDictObj = appendCropToPipe(clippingMask, args.out_epsg)

    if args.clean == True:
        myDictObj = appendNoiseFilterToPipe()
        myDictObj = appendElmFilterToPipe()

    if args.classify == True:
        myDictObj = appendSmrfFilterToPipe()
        myDictObj = append_neighbor_classifier()
    filename = args.output_filename.split('.')[0]+"_dsm."+args.output_filename.split('.')[1]
    print(filename, "dsm.")
    myDictObj = appendGtiffWriterToPipe(1, "scratch"+filename, args.resolution)

    with open ('scratchpipeline.json', 'w') as outfile:
        json.dump(myDictObj, outfile)
    os.system("pdal pipeline scratchpipeline.json")
    interpolate(filename, "_dsm.")
    cleanup()
if args.contour==1 and args.dtm==0:
    print("Error, no dtm found to produce contour lines")
elif args.contour ==1 and args.dtm==1:
    output_contour()
