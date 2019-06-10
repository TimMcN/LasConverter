
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

myDictObj = {}

def arguments():
    parser = argparse.ArgumentParser(description='LAS/LAZ -> GTiff Converter')
    parser.add_argument('input_filename')
    parser.add_argument('output_filename')
    parser.add_argument('--resolution', type=int, default=1,
                        help = "Set the resolution of the output GTiff")
    parser.add_argument('--clip', type=str,
                        help = "--clip <file_path>, clip output to a SHP/KML/GeoJSON")
    parser.add_argument('--dtm', type=int, default=0,
                        help="--dtm <1> to output a DTM, defaults to outputting a DEM")
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

def interpolate():
    if args.clip is not None:
        wktPolygonToShapefile(getPolygon())

        os.system("saga_cmd grid_tools 7 -INPUT "+"scratch"+args.output_filename + " -RESULT scratch")
        os.system("saga_cmd grid_tools 31 -GRIDS scratch.sgrd -POLYGONS scratch.shp -CLIPPED scratchtes6 -EXTENT 3")
        os.system("saga_cmd io_gdal 2 -GRIDS scratchtes6.sgrd -FILE "+ args.output_filename)
    else:
        os.system("saga_cmd grid_tools 7 -INPUT "+"scratch"+args.output_filename + " -RESULT scratch")
        os.system("saga_cmd io_gdal 2 -GRIDS scratch.sgrd -FILE "+ args.output_filename)

def cleanup():
    files = os.listdir()
    for file in files:
        if (file.startswith("scratch")):
            os.remove(file)


args = arguments()
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

#If DTM is being exported, add classification pipes with writer. For writer pipe, use output:min
if args.dtm == 1:
        myDictObj = appendGroundFilter()
        myDictObj = appendGtiffWriterToPipe(1, "scratch"+args.output_filename, args.resolution)
elif args.dtm == 0:
    myDictObj = appendGtiffWriterToPipe(0, "scratch"+args.output_filename, args.resolution)
with open ('scratchpipeline.json', 'w') as outfile:
    json.dump(myDictObj, outfile)
os.system("pdal pipeline scratchpipeline.json")


interpolate()
cleanup()
