# Spec

## Problem
The Automobile Maintenance Genie (AMG) is a tool which I want to develop to help me keep track of maintenance activities related to automobiles which I own.  

## Solution
I'd like to have the tool review the manufacturer suggested maintenance routine / schedule for my selected automobile as the baseline maintenance schedule which should be followed.  I have collected maintenance receipts from almost all service performed on my automobile.  I will scan the receipts into an common image (PNG, JPG, GIF) or PDF format and then send the receipts to AMG so that the AMG can track the maintenance performed on my vehicle and compare the maintenance vs the baseline schedule.  This will help me to identify maintenance gaps and suggest required maintenance that I have missed.  It will also alert me to upcoming / future maintenance actions and predict the costs of the future maintenance so that I can appropriately budget money for the maintenance.

## Goals
- AMG should be easy to use
- Identify maintenance 'gaps'
- Alert me to future required maintenance
- Approximate future costs for budgeting purposes

## Features
- [x] AMG must support more than one automobile.
- [x] AMG should allow the user to generate flexible, on-demand reports so that I can review prior maintenance history
- [x] AMG will need to be able to parse PDF documents and extract maintenance history
- [x] AMG will need to be able to parse PNG, JPG or GIF documents and extract maintenance history
- [x] AMG will need it's own self contained data storage mechanism
- [x] AMG should be web-based; compatible with mobile, tablet and desktop web-browsers
- [x] Tesseract, PyMuPDF, Mathpix, Claude can all be used to work with PDFs
- [x] AMG should also allow the user to enter self-service maintenance information
- [x] AMG should also allow the user to track fuel usage information (cost, fuel economy, etc)

## Constraints
- Runs on home lab; prefer low-cost solutions over paid APIs
