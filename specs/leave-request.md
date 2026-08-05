# Functional Specification: Employee Leave Request

## 1. Purpose

Employees currently request leave by emailing their manager. There is no
central record of balances or approvals. This application lets employees
create leave requests, managers approve or reject them, and HR see an
overview of planned absences.

## 2. Scope

In scope: creating a leave request with type and dates, submitting it for
approval, and tracking status.

Out of scope: payroll posting, calendar synchronisation, and automatic
balance calculation against time management.

## 3. Business Objects

### 3.1 Leave Request

Each request has a request number (format LR-000001), the employee ID and
display name, leave type (Annual, Sick, Compensatory, Unpaid), start date,
end date, number of days, and a free-text reason.

Status values: Draft, Submitted, Approved, Rejected, Cancelled. New
requests start as Draft.

Optional: a manager comment when approving or rejecting.

We need created/modified tracking on every request.

### 3.2 Employee (reference)

Employees are maintained in HR master data and are read-only here. We hold
employee number, full name, department, and email.

## 4. User Interface

The main screen is a list of leave requests showing request number,
employee name, leave type, start date, end date, days, and status.

Users filter by status, leave type, and employee.

Opening a request shows general information (request number, employee,
type, dates, days, reason) and an approval section (status, manager
comment). Employees create and edit their own drafts. Managers change
status; employee master data is display-only.

## 5. Authorisation

Only authenticated users may access the service.
