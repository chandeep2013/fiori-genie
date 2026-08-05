# Functional Specification: Travel Expense Claim

## 1. Purpose

Employees submit travel expenses by emailing scanned receipts. Finance
cannot see open claims or enforce cost centres. This application captures
expense claims with line items for meals, travel, and lodging, linked to a
trip and cost centre.

## 2. Scope

In scope: expense claim header and items, cost centre, trip dates, totals,
and approval status.

Out of scope: receipt OCR, credit-card feed, and payment run.

## 3. Business Objects

### 3.1 Expense Claim (header)

Each claim has a claim number (format EX-000001), employee name, trip
purpose, trip start date, trip end date, total amount, currency, and cost
centre (10 characters).

Status: Draft, Submitted, Approved, Rejected, Paid. New claims start as
Draft.

Created/modified tracking is required.

### 3.2 Expense Item

A claim has one or more items. An item cannot exist without its claim.
Each item has a position, expense category (Travel, Meal, Lodging, Other),
expense date, description, amount, and currency.

### 3.3 Cost Centre (reference)

Cost centres are maintained in controlling and are read-only here. We hold
cost centre code, name, and company code.

## 4. User Interface

The main screen lists claims: claim number, employee, trip purpose,
status, total amount, currency, cost centre.

Users filter by status, employee, and cost centre.

Opening a claim shows general information (claim number, employee,
purpose, trip dates, status) and commercial data (cost centre, total,
currency), plus an items table (position, category, date, description,
amount, currency).

Users create and edit claims and items with draft handling. Cost centres
are display-only.

## 5. Authorisation

Only authenticated users may access the service.
