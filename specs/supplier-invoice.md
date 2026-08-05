# Functional Specification: Supplier Invoice Intake

## 1. Purpose

Accounts payable receives supplier invoices by email and enters them
manually. Mistakes and duplicates are common. This application captures
incoming invoices with header and line items against a supplier and
purchase order reference, ready for later posting.

## 2. Scope

In scope: invoice header and items, supplier, invoice date, due date,
gross and tax amounts, and processing status.

Out of scope: automatic 3-way match, OCR extraction, and FI document
posting.

## 3. Business Objects

### 3.1 Supplier Invoice (header)

Each invoice has an invoice number (external supplier document number, up
to 16 characters), our internal reference (format SI-000001), invoice
date, due date, gross amount, tax amount, net amount, currency, and an
optional purchase order number.

Status: Draft, In Review, Posted, Blocked, Cancelled. New invoices start
as Draft.

It references a supplier. Created/modified tracking is required.

### 3.2 Invoice Item

An invoice has one or more items. An item cannot exist without its
invoice. Each item has a position, material or service text, quantity,
unit, unit price, and line amount.

### 3.3 Supplier (reference)

Suppliers are maintained in master data and are read-only here. We hold
supplier name, country, VAT registration number, and payment terms.

## 4. User Interface

The main screen lists invoices: internal reference, supplier invoice
number, supplier, status, invoice date, due date, gross amount, currency.

Users filter by status, supplier, and invoice date.

Opening an invoice shows general information (references, dates, status,
PO number) and amounts (net, tax, gross, currency, supplier), plus an
items table (position, description, quantity, unit, unit price, amount).

Users create and edit invoices and items with draft handling. Suppliers
are display-only.

## 5. Authorisation

Only authenticated users may access the service.
