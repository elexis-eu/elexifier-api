#!/bin/bash

echo "Installing libxml2, libmotif-dev, build-essential"
echo "y" | sudo apt-get install libxml2 libmotif-dev build-essential

echo "Downloading pdf2xml"
wget https://cloud.elex.is/s/CNq9oA7EWQboR4W/download -O pdf2xml.tar.gz

echo "Extracting files from pdf2xml.tar.gz"
tar -zxvf pdf2xml.tar.gz

echo "Compiling pdf2xml"
cd pdf2xml; sudo make; cd ..

echo "Copying pdftoxml to directory: elexifier-api/app/transformator/pdftoxml"
cp pdf2xml/exe/pdftoxml ./app/modules/transformator/

echo "Cleaning up"
echo "y" | rm -r pdf2xml.tar.gz
echo "y" | rm -r pdf2xml


