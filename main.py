
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
                        help="--dtm <1> to output a DTM, defaults to outputting a DEM. Clipping File is recommended for this option")
    parser.add_argument('--in_epsg', type =str, default="2157",
                        help = "--InEPSG <EPSG Code>, if left blank input EPSG is assumed to be 2157")
    parser.add_argument('--out_epsg', type =str, default="2157",
                        help = "--OutEPSG <EPSG Code>, if left blank output EPSG is defaults to 2157")

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

def createShapefile(polygon):
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
    if filename.split('.')[1]=="las":
        epsg = in_epsg
        myDictObj = {"pipeline":[{"type": "readers.las", "spatialreference": "EPSG:"+epsg,
        "filename":filename},
        {"type":"filters.reprojection", "in_srs": "EPSG:"+in_epsg,
        "out_srs":"EPSG:"+out_epsg},
        ]}
        return myDictObj
    else:
        print("Error: Invalid input file")

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
    "window":16,
    "threshold":0.45,
    "scalar":1.2
    })
    return myDictObj

def appendGroundClassification():
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

def cleanup():
    files = os.listdir()
    for file in files:
        if (file.startswith("scratch")):
            os.remove(file)

args = arguments()
myDictObj = buildPipeInput(args.in_epsg, args.out_epsg, args.input_filename)
print("1")
#Check for clipping file
if args.clip is not None:
    #Build clipping pipe
    clippingMask = getPolygon()
    myDictObj = appendCropToPipe(clippingMask, args.out_epsg)

#If DTM is being exported, add classification pipes with writer. For writer pipe, use output:min
if args.dtm == 1:
        myDictObj = appendGroundClassification()
        myDictObj = appendGtiffWriterToPipe(1, "scratch"+args.output_filename, args.resolution)
elif args.dtm == 0:
    myDictObj = appendGtiffWriterToPipe(0, "scratch"+args.output_filename, args.resolution)
    print("2")
with open ('scratchpipeline.json', 'w') as outfile:
    json.dump(myDictObj, outfile)
print("3")
os.system("pdal pipeline scratchpipeline.json")
print("4")


if args.clip is not None:
    createShapefile(getPolygon())

    os.system("saga_cmd grid_tools 7 -INPUT "+"scratch"+args.output_filename + " -RESULT scratch")
    os.system("saga_cmd grid_tools 31 -GRIDS scratch.sgrd -POLYGONS scratch.shp -CLIPPED scratchtes6 -EXTENT 3")
    os.system("saga_cmd io_gdal 2 -GRIDS scratchtes6.sgrd -FILE "+ args.output_filename)
else:
    os.system("saga_cmd grid_tools 7 -INPUT "+"scratch"+args.output_filename + " -RESULT scratch")
    os.system("saga_cmd io_gdal 2 -GRIDS scratch.sgrd -FILE "+ args.output_filename)

cleanup()
