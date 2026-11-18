-- 1. Application type / stage / step combos
SELECT '1 App steps' AS chk,
       CAST(Application_Type__c AS nvarchar(255)) AS v1,
       CAST(Process_Stage__c    AS nvarchar(255)) AS v2,
       CAST(Process_Step__c     AS nvarchar(255)) AS v3,
       COUNT(*) AS n
FROM dbo.Application
WHERE IsDeleted = 0
GROUP BY Application_Type__c, Process_Stage__c, Process_Step__c

UNION ALL -- 2. Unit status / type / subtype values
SELECT '2 Unit values', CAST(Status__c AS nvarchar(255)),
       CAST(Type__c AS nvarchar(255)), CAST(Sub_type__c AS nvarchar(255)), COUNT(*)
FROM dbo.Statistic
WHERE IsDeleted = 0
GROUP BY Status__c, Type__c, Sub_type__c

UNION ALL -- 3. What ScdEndDate looks like (NULL vs far-future year)
SELECT '3 SCD end year', ISNULL(CAST(YEAR(ScdEndDate) AS nvarchar(255)), 'NULL'),
       NULL, NULL, COUNT(*)
FROM dbo.Statistic
GROUP BY YEAR(ScdEndDate)

UNION ALL -- 4. Orphan units (no matching application)
SELECT '4 Orphan units', NULL, NULL, NULL, COUNT(*)
FROM dbo.Statistic S
LEFT JOIN dbo.Application A ON S.Application__c = A.Id
WHERE A.Id IS NULL

UNION ALL -- 5. Application Ids that appear more than once
SELECT '5 Dup app Ids', NULL, NULL, NULL, COUNT(*)
FROM (SELECT Id FROM dbo.Application GROUP BY Id HAVING COUNT(*) > 1) d

UNION ALL -- 6. Statistic row count vs distinct units
SELECT '6 Stat rows / distinct Ids',
       CAST(COUNT(DISTINCT Id) AS nvarchar(255)), NULL, NULL, COUNT(*)
FROM dbo.Statistic

UNION ALL -- 7. Which application types units link to
SELECT '7 Units by app type', CAST(A.Application_Type__c AS nvarchar(255)),
       NULL, NULL, COUNT(*)
FROM dbo.Statistic S
JOIN dbo.Application A ON S.Application__c = A.Id
GROUP BY A.Application_Type__c

ORDER BY chk, v1, v2, v3;