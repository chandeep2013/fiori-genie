# Functional Specification: Sales Quotation

## 1. Purpose

Sales colleagues prepare customer quotations in Excel and re-type them into
ERP. This application lets them capture a quotation with customer and line
items, track validity and status, and hand off a clean document for order
conversion later.

## 2. Scope

In scope: quotation header and items, customer assignment, validity dates,
net value and currency, and status tracking.

Out of scope: pricing engine, ATP check, PDF output, and conversion to
sales order.

## 3. Business Objects

### 3.1 Sales Quotation (header)

Each quotation has a quotation number (format SQ-000001), a description,
valid-from and valid-to dates, net value, currency (3 characters), and
sales organisation (4 characters).

Status: Draft, Sent, Accepted, Rejected, Expired. New quotations start as
Draft.

It references a customer. Created/modified tracking is required.

### 3.2 Quotation Item

A quotation has one or more items. An item cannot exist without its
quotation. Each item has a position, material number, description,
quantity (decimal), unit of measure, unit price, and line net amount.

### 3.3 Customer (reference)

Customers are maintained in master data and are read-only here. We hold
customer number, name, country, and payment terms text.

## 4. User Interface

The main screen lists quotations: number, description, customer, status,
valid-to, net value, currency.

Users filter by status, customer, and quotation number.

Opening a quotation shows general information (number, description,
status, sales org, validity) and commercial data (customer, net value,
currency), plus an items table (position, material, description,
quantity, unit, unit price, net amount).

Users create and edit quotations and items with draft handling. Customers
are display-only.

## 5. Authorisation

Only authenticated users may access the service.
