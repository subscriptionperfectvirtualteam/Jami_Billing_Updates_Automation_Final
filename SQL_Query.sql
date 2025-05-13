-- Declare input parameters
DECLARE @clientName NVARCHAR(100) = 'Primeritus Specialized - IBEAM';
DECLARE @lienholderName NVARCHAR(100) = 'Global CU fka Alaska USA FCU';
DECLARE @feeTypeName NVARCHAR(100) = 'Involuntary Repo';

-- Get foreign keys from names
DECLARE @clientId INT = (SELECT TOP 1 id FROM dbo.RDN_Client WHERE client_name = @clientName);
DECLARE @lienholderId INT = (SELECT TOP 1 id FROM dbo.Lienholder WHERE lienholder_name = @lienholderName);
DECLARE @feeTypeId INT = (SELECT TOP 1 id FROM dbo.FeeType WHERE fee_type_name = @feeTypeName);

-- Check if a matching FeeDetails2 record exists
IF EXISTS (
    SELECT 1 
    FROM dbo.FeeDetails2 
    WHERE client_id = @clientId AND lh_id = @lienholderId AND ft_id = @feeTypeId
)
BEGIN
    -- Return result with names
    SELECT 
        fd.fd_id,
        c.client_name,
        lh.lienholder_name,
        ft.fee_type_name,
        fd.amount
    FROM dbo.FeeDetails2 fd
    JOIN dbo.RDN_Client c ON fd.client_id = c.id
    JOIN dbo.Lienholder lh ON fd.lh_id = lh.id
    JOIN dbo.FeeType ft ON fd.ft_id = ft.id
    WHERE fd.client_id = @clientId AND fd.lh_id = @lienholderId AND fd.ft_id = @feeTypeId;
END
ELSE
BEGIN
    -- Get ID for 'Standard' lienholder
    DECLARE @standardLienholderId INT = (
        SELECT TOP 1 id FROM dbo.Lienholder WHERE lienholder_name = 'Standard'
    );

    -- Return fallback result with names
    SELECT 
        fd.fd_id,
        c.client_name,
        lh.lienholder_name,
        ft.fee_type_name,
        fd.amount
    FROM dbo.FeeDetails2 fd
    JOIN dbo.RDN_Client c ON fd.client_id = c.id
    JOIN dbo.Lienholder lh ON fd.lh_id = lh.id
    JOIN dbo.FeeType ft ON fd.ft_id = ft.id
    WHERE fd.client_id = @clientId AND fd.lh_id = @standardLienholderId AND fd.ft_id = @feeTypeId;
END
