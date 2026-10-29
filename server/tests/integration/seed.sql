-- Seed data for connector integration tests. Batches are separated by GO lines.
-- Idempotent: the database is dropped and rebuilt.

IF DB_ID('magbi_test') IS NOT NULL
BEGIN
    ALTER DATABASE magbi_test SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE magbi_test;
END
GO
CREATE DATABASE magbi_test;
GO
USE magbi_test;
GO
IF SUSER_ID('magbi_ro') IS NOT NULL DROP LOGIN magbi_ro;
GO
CREATE LOGIN magbi_ro WITH PASSWORD = 'MagBI_Ro_Passw0rd!', CHECK_POLICY = OFF;
CREATE USER magbi_ro FOR LOGIN magbi_ro;
ALTER ROLE db_datareader ADD MEMBER magbi_ro;
GO
CREATE SCHEMA sales;
GO

-- Every supported type, with a full row, an all-NULL row and a unicode/edge row.
CREATE TABLE dbo.all_types (
    id            int            NOT NULL PRIMARY KEY,
    c_bigint      bigint         NULL,
    c_int         int            NULL,
    c_smallint    smallint       NULL,
    c_tinyint     tinyint        NULL,
    c_bit         bit            NULL,
    c_decimal     decimal(18,2)  NULL,
    c_decimal_big decimal(38,10) NULL,
    c_numeric     numeric(10,0)  NULL,
    c_money       money          NULL,
    c_smallmoney  smallmoney     NULL,
    c_float       float          NULL,
    c_real        real           NULL,
    c_char        char(5)        NULL,
    c_varchar     varchar(50)    NULL,
    c_nchar       nchar(5)       NULL,
    c_nvarchar    nvarchar(100)  NULL,
    c_guid        uniqueidentifier NULL,
    c_date        date           NULL,
    c_datetime    datetime       NULL,
    c_datetime2   datetime2(6)   NULL,
    c_smalldt     smalldatetime  NULL,
    c_time        time(6)        NULL,
    c_varbinary   varbinary(16)  NULL,
    c_binary      binary(4)      NULL
);
GO
INSERT INTO dbo.all_types VALUES
(1, 9223372036854775807, 2147483647, 32767, 255, 1, 12345678901234.56,
 1234567890123456789012345678.1234567890, 1234567890, 922337203685477.5807, 214748.3647,
 3.141592653589793, 1.5, 'abc', 'hello', N'ab', N'héllo wörld', '6F9619FF-8B86-D011-B42D-00C04FC964FF',
 '2024-02-29', '2024-02-29 13:14:15.123', '2024-02-29 13:14:15.123456', '2024-02-29 13:15:00',
 '13:14:15.123456', 0xDEADBEEF, 0x01020304),
(2, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
 NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
(3, -9223372036854775808, -2147483648, -32768, 0, 0, -0.01,
 -1.0000000001, -1, -922337203685477.5808, -214748.3648,
 -1.7976931348623157E+308, -3.4E+38, '', '', N'', N'日本語 😀 Ж', '00000000-0000-0000-0000-000000000000',
 '0001-01-01', '1753-01-01', '0001-01-01 00:00:00', '1900-01-01 00:00:00',
 '00:00:00', 0x, 0x00000000);
GO

-- Types without a native mapping; the connector must degrade them to strings.
CREATE TABLE dbo.exotic_types (
    id        int NOT NULL PRIMARY KEY,
    c_xml     xml NULL,
    c_geo     geography NULL,
    c_hier    hierarchyid NULL,
    c_variant sql_variant NULL,
    c_dto     datetimeoffset(7) NULL
);
GO
INSERT INTO dbo.exotic_types VALUES
(1, '<a>1</a>', geography::Point(47.6, -122.3, 4326), hierarchyid::Parse('/1/2/'),
 CAST(42 AS sql_variant), '2024-03-01 12:00:00.1234567 +03:00'),
(2, NULL, NULL, NULL, NULL, NULL);
GO

-- Awkward identifiers must be quoted correctly end to end.
CREATE TABLE sales.[Order Lines] (
    [Line ID]  int NOT NULL PRIMARY KEY,
    [Qty]      int NOT NULL,
    [Note]     nvarchar(50) NULL,
    [a]]b]     int NULL
);
GO
INSERT INTO sales.[Order Lines] ([Line ID], [Qty], [Note], [a]]b])
SELECT TOP (200000)
    ROW_NUMBER() OVER (ORDER BY (SELECT NULL)),
    ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) % 7,
    CASE WHEN ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) % 10 = 0 THEN NULL ELSE N'line ö' END,
    1
FROM sys.all_objects a CROSS JOIN sys.all_objects b;
GO
CREATE TABLE sales.composite_key (
    a int NOT NULL,
    b int NOT NULL,
    v nvarchar(10) NULL,
    CONSTRAINT pk_composite PRIMARY KEY (a, b)
);
GO
INSERT INTO sales.composite_key VALUES (1, 1, N'x'), (1, 2, N'y');
GO
CREATE VIEW sales.big_lines AS
SELECT [Line ID], [Qty] FROM sales.[Order Lines] WHERE [Qty] >= 5;
GO
CREATE TABLE dbo.empty_table (id int NOT NULL PRIMARY KEY);
GO
