-- Run once against the existing Loan Lifecycle Guardian SQL Server database.
IF OBJECT_ID(N'dbo.service_requests', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.service_requests (
        id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        user_id INT NOT NULL,
        loan_id INT NULL,
        category VARCHAR(30) NOT NULL,
        subject VARCHAR(120) NOT NULL,
        message VARCHAR(1000) NOT NULL,
        status VARCHAR(20) NOT NULL CONSTRAINT DF_service_requests_status DEFAULT ('OPEN'),
        response VARCHAR(1000) NULL,
        handled_by INT NULL,
        created_at DATETIME NOT NULL CONSTRAINT DF_service_requests_created_at DEFAULT (GETDATE()),
        resolved_at DATETIME NULL,
        CONSTRAINT FK_service_requests_users FOREIGN KEY (user_id) REFERENCES dbo.users(id)
    );
    CREATE INDEX IX_service_requests_user_id ON dbo.service_requests(user_id);
    CREATE INDEX IX_service_requests_status ON dbo.service_requests(status);
END;
GO
