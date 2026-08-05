# Functional Specification: Purchase Requisition Management

## 1. Purpose

Plant maintenance and production staff need to raise purchase requisitions for
materials and services before a purchase order is created. Today this happens in
a shared spreadsheet, which gives no approval trail and no visibility of open
demand. This application replaces that spreadsheet.

## 2. Scope

In scope: capturing a requisition with its line items, assigning a preferred
supplier, and moving the requisition through a simple approval status.

Out of scope: the approval workflow engine itself, budget checks, and the
conversion of an approved requisition into a purchase order.

## 3. Business Objects

### 3.1 Purchase Requisition (header)

Each requisition is identified by a requisition number in the format PR-000001,
assigned externally. It carries a short title describing what is being
requested, the name of the requester, the cost centre it should be charged to,
and the date by which the goods or services are needed.

A requisition has a status: Draft, Submitted, Approved or Rejected. New
requisitions start as Draft.

The requisition records the total estimated value and the currency, and may name
a preferred supplier. The preferred supplier is optional at the time of
creation.

We need to know who created each requisition and when, and who last changed it.

### 3.2 Requisition Item

A requisition has one or more line items. A line item cannot exist without its
requisition. Each item has a position number, a material number, a free-text
description, the quantity required, the unit of measure, and an estimated price
per unit.

### 3.3 Supplier

Suppliers are maintained centrally in another system and are read-only here. We
hold the supplier name, the two-character country code, a contact email address,
and a performance rating between 0.00 and 5.00.

## 4. User Interface

The main screen is a list of purchase requisitions. Users need to see the
requisition number, its title, the current status, the preferred supplier, the
total value and the date needed, without opening each one.

Users filter this list most often by status, by requisition number, and by
supplier.

Opening a requisition shows its details grouped into a general section
(requisition number, title, status, requester, cost centre, date needed) and a
commercial section (preferred supplier, total value, currency). Below those, the
line items are shown in a table with position, material, description, quantity,
unit and unit price.

Users must be able to create and edit a requisition and its items, with changes
held as a draft until they are explicitly saved. Suppliers are display-only.

## 5. Authorisation

Only authenticated users may access the service.
