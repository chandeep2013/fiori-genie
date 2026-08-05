# Functional Specification: Maintenance Notification

## 1. Purpose

Plant technicians report equipment failures on paper sheets that get lost
before planning can act. This application captures maintenance
notifications against technical objects, with priority and damage details,
so planners can triage work.

## 2. Scope

In scope: creating a notification with header and item lines for damaged
parts, assigning priority and technical object, and tracking lifecycle
status.

Out of scope: work order creation, spare-parts reservation, and mobile
offline sync.

## 3. Business Objects

### 3.1 Maintenance Notification (header)

Each notification has a notification number (format MN-000001), a short
title, description, priority (Low, Medium, High, Emergency), notification
type (Breakdown, Preventive, Inspection), reported-by name, and reported
date.

Status: Draft, Open, In Progress, Completed, Cancelled. New notifications
start as Draft.

It references a technical object (equipment). Created/modified tracking is
required.

### 3.2 Notification Item

A notification has one or more items. An item cannot exist without its
notification. Each item has a position, damage code, damage text, cause
text, and estimated repair hours (decimal).

### 3.3 Equipment (reference)

Equipment is maintained in plant maintenance master data and is read-only
here. We hold equipment number, description, plant, and functional location.

## 4. User Interface

The main screen lists notifications: number, title, priority, type,
equipment, status, reported date.

Users filter by status, priority, and equipment.

Opening a notification shows general data (number, title, description,
type, priority, reported by/date, equipment) and a table of items
(position, damage code, damage text, cause, hours).

Users create and edit notifications and items in draft until saved.
Equipment is display-only.

## 5. Authorisation

Only authenticated users may access the service.
