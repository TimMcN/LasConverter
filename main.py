
import os
import argparse
import geojson
import json
import shapefile
import shapely.wkt
from shapely.geometry import shape
from pykml import parser
from osgeo import gdal, ogr

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


def buildPipeInput(in_epsg,out_epsg, filename):
    epsg = "2157"
    filename = "Maynooth.las"
    myDictObj = {"pipeline":[{"type": "readers.las", "spatialreference": "EPSG:"+epsg,
    "filename":filename},
    {"type":"filters.reprojection", "in_srs": "EPSG:"+in_epsg,
    "out_srs":"EPSG:"+out_epsg},
    ]}
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

args = arguments()
myDictObj = buildPipeInput(args.in_epsg, args.out_epsg, args.input_filename)
#Check for clipping file
if args.clip is not None:
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
        #Build clipping pipe
    myDictObj = appendCropToPipe(clippingMask, args.out_epsg)

#If DTM is being exported, add classification pipes with writer. For writer pipe, use output:min
if args.dtm == 1:
    myDictObj = appendGroundClassification()
    #myDictObj = appendSmrfFilterToPipe()
    myDictObj = appendGtiffWriterToPipe(1, args.output_filename, args.resolution)
#If DEM is being exported add writer pipe use output:"mean"
elif args.dtm == 0:
    myDictObj = appendGtiffWriterToPipe(0, args.output_filename, args.resolution)

with open ('pipeline.json', 'w') as outfile:
    json.dump(myDictObj, outfile)

os.system("pdal pipeline pipeline.json")
