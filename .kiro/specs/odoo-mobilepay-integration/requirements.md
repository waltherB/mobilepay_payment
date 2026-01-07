# Requirements Document

## Introduction

This specification defines the requirements for developing an Odoo 17 payment provider module that integrates with Vipps MobilePay ePayment API v3, tailored specifically for the Danish market (DKK). The module must support authorize & capture payment flows with deferred payment capture, immediate payments, refunds, webhook integration, and enhanced checkout UX with phone number pre-fill functionality.

## Glossary

- **MobilePay_API**: Vipps MobilePay ePayment API v3 for Danish market integration
- **Payment_Provider**: Odoo 17 payment provider module for MobilePay integration
- **Authorize_Capture_Flow**: Two-phase payment process where funds are authorized at checkout but captured only upon order shipment
- **Webhook_Handler**: Component that processes real-time payment event notifications from MobilePay
- **Transaction_Manager**: Component that manages payment transaction states and operations
- **Authentication_Service**: OAuth2 token management service for MobilePay API access
- **Configuration_Manager**: Backend interface for configuring MobilePay provider settings
- **Checkout_Interface**: Frontend payment method selection and processing interface

## Requirements

### Requirement 1: Backend Configuration Management

**User Story:** As a system administrator, I want to configure MobilePay payment provider settings, so that I can establish secure API connectivity and manage payment processing options.

#### Acceptance Criteria

1. THE Configuration_Manager SHALL provide fields for MobilePay client ID, encrypted client secret, subscription key, merchant serial number, and webhook credentials
2. WHEN webhook registration is triggered, THE Configuration_Manager SHALL send POST request to MobilePay webhooks endpoint with proper event subscriptions
3. WHEN webhook registration succeeds, THE Configuration_Manager SHALL store webhook ID and secret in encrypted fields
4. THE Configuration_Manager SHALL validate webhook connectivity by sending test payload simulation
5. THE Configuration_Manager SHALL provide manual capture toggle and optional auto-capture delay configuration

### Requirement 2: OAuth2 Authentication and API Headers

**User Story:** As a payment system, I want to maintain secure API authentication, so that all MobilePay API requests are properly authorized and include required headers.

#### Acceptance Criteria

1. THE Authentication_Service SHALL implement OAuth2 token management with automatic refresh on expiry
2. WHEN API token expires or returns 401 response, THE Authentication_Service SHALL automatically refresh the token and retry the request once
3. THE Authentication_Service SHALL cache tokens in secure configuration parameters
4. WHEN token refresh fails repeatedly, THE Authentication_Service SHALL log failures and notify administrators
5. THE Authentication_Service SHALL include mandatory Vipps system headers in every API request including system name, version, plugin details, authorization, subscription key, and merchant serial number

### Requirement 3: Payment Initiation and Checkout Flow

**User Story:** As a customer, I want to complete payments using MobilePay during checkout, so that I can pay for my orders using my preferred mobile payment method.

#### Acceptance Criteria

1. WHEN payment is initiated, THE Payment_Provider SHALL send POST request to MobilePay payments endpoint with idempotency key, user flow, payment method, customer details, merchant info, and transaction data
2. THE Payment_Provider SHALL convert order amounts from DKK to øre for API communication
3. WHEN customer phone number is available, THE Checkout_Interface SHALL auto-format it to E.164 format and include in payment request
4. THE Payment_Provider SHALL generate unique transaction reference and store idempotency key to prevent duplicate payments
5. THE Payment_Provider SHALL redirect customer to MobilePay payment interface with proper callback configuration

### Requirement 4: Return Handling and Active Status Polling

**User Story:** As a payment system, I want to actively monitor payment status, so that transaction states are updated promptly even when webhooks are delayed or missed.

#### Acceptance Criteria

1. WHEN customer returns from MobilePay interface, THE Transaction_Manager SHALL immediately poll payment status via GET request
2. THE Transaction_Manager SHALL map MobilePay status RESERVED to Odoo authorized state
3. THE Transaction_Manager SHALL map MobilePay status CAPTURED to Odoo done state  
4. THE Transaction_Manager SHALL map MobilePay status CANCELLED or EXPIRED to Odoo cancel state
5. WHEN payment status is pending, THE Transaction_Manager SHALL retry polling every 30 seconds for maximum 5 minutes

### Requirement 5: Webhook Security and Event Processing

**User Story:** As a payment system, I want to securely process real-time payment notifications, so that transaction states are updated immediately when payment events occur.

#### Acceptance Criteria

1. WHEN webhook request is received, THE Webhook_Handler SHALL verify X-Request-Signature header against stored webhook secret using HMAC-SHA256
2. IF webhook signature verification fails, THEN THE Webhook_Handler SHALL reject request with HTTP 403 status
3. WHEN payment.reserved event is received, THE Webhook_Handler SHALL set transaction to authorized state
4. WHEN payment.captured event is received, THE Webhook_Handler SHALL set transaction to done state
5. WHEN payment.cancelled event is received, THE Webhook_Handler SHALL set transaction to cancel state and send customer notification
6. WHEN payment.refunded event is received, THE Webhook_Handler SHALL update refund status and reconcile with account payment records

### Requirement 6: Authorize and Capture Payment Flow

**User Story:** As a merchant, I want to authorize payments at checkout but capture funds only when orders are shipped, so that I comply with payment processing best practices and avoid premature fund capture.

#### Acceptance Criteria

1. WHEN capture_manually setting is enabled, THE Transaction_Manager SHALL authorize payments without immediate capture
2. WHEN order shipment is completed and transaction is in authorized state, THE Transaction_Manager SHALL provide manual capture functionality
3. WHEN manual capture is triggered, THE Transaction_Manager SHALL send POST request to MobilePay capture endpoint with transaction amount
4. THE Transaction_Manager SHALL validate that order is in shipped state before allowing capture
5. WHEN capture_manually is disabled, THE Transaction_Manager SHALL automatically capture authorized payments based on configured delay

### Requirement 7: Refund Processing

**User Story:** As a merchant, I want to process full and partial refunds for MobilePay transactions, so that I can handle returns and customer service requests appropriately.

#### Acceptance Criteria

1. THE Transaction_Manager SHALL support multiple partial refunds per transaction via POST request to MobilePay refund endpoint
2. WHEN refund is processed, THE Transaction_Manager SHALL link refunds to Odoo account payment records
3. THE Transaction_Manager SHALL update payment transaction with refunded amounts
4. THE Transaction_Manager SHALL validate that refund amount does not exceed captured amount
5. THE Transaction_Manager SHALL track cumulative refunded amounts across multiple partial refunds

### Requirement 8: User Experience and Phone Number Pre-fill

**User Story:** As a customer, I want a streamlined checkout experience with my phone number pre-filled, so that I can bypass MobilePay's login page and complete payments quickly.

#### Acceptance Criteria

1. WHEN customer has phone number in profile, THE Checkout_Interface SHALL auto-format it to E.164 format
2. THE Checkout_Interface SHALL include formatted phone number in MobilePay payment request customer data
3. THE Checkout_Interface SHALL display MobilePay payment option with official branding and Danish language labels
4. THE Checkout_Interface SHALL disable express checkout to force full redirect to MobilePay interface
5. THE Checkout_Interface SHALL handle payment redirects and return flows seamlessly

### Requirement 9: Security and Data Protection

**User Story:** As a system administrator, I want sensitive payment data to be properly encrypted and secured, so that the system complies with security requirements and protects confidential information.

#### Acceptance Criteria

1. THE Configuration_Manager SHALL encrypt sensitive fields including client secret, subscription key, and webhook secret in database storage
2. THE Authentication_Service SHALL securely store and manage OAuth2 tokens using Odoo's configuration parameter system
3. THE Webhook_Handler SHALL validate all incoming webhook requests using cryptographic signature verification
4. THE Payment_Provider SHALL use HTTPS for all API communications with MobilePay
5. THE Configuration_Manager SHALL provide secure credential management without exposing sensitive data in logs or user interfaces

### Requirement 10: Module Structure and Compatibility

**User Story:** As a developer, I want the module to follow Odoo standards and be compatible with both Enterprise and Community editions, so that it integrates properly with existing Odoo installations.

#### Acceptance Criteria

1. THE Payment_Provider SHALL be compatible with Odoo 17 Enterprise and Community editions
2. THE Payment_Provider SHALL integrate with Odoo's native payment, account, and website_sale modules
3. THE Payment_Provider SHALL follow standard Odoo module directory structure with models, controllers, data, views, and static assets
4. THE Payment_Provider SHALL support DKK currency exclusively with proper conversion to øre for API calls
5. THE Payment_Provider SHALL include Danish language translations for all user-facing text