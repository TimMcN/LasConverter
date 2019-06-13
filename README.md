# LasConverter
Converts LAS/LAZ Files (LIDAR data) to DSM/DEMs.
Output can be clipped with a shapefile (KML/SHP/GeoJson)
Input and output EPSGS can be specified as their number codes where neccessary


## Dependencies:

###### PDAL (Point Data And Abstraction Library)

###### SAGA (System for Automated Geoscentific Analyses)

## Usage:


```           
usage: main.py [-h] [--resolution RESOLUTION] [--clip CLIP] [--dtm DTM]
               [--dsm DSM] [--contour CONTOUR] [--in_epsg IN_EPSG]
               [--out_epsg OUT_EPSG] [--classify CLASSIFY] [--clean CLEAN]
               input_filename output_filename
```
