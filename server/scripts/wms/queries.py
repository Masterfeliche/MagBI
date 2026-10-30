"""Read-only MSD_ERP table queries for the three MagBI Warehouse dashboards (W1, W4, W7)."""

WH = "COALESCE(NULLIF(LTRIM(RTRIM({a}.WareHouseName)), ''), 'Not set')"

CATEGORY = """CASE NULLIF(LTRIM(RTRIM({c})), '')
    WHEN 'PH' THEN 'Pharmaceuticals' WHEN 'LB' THEN 'Laboratory' WHEN 'MS' THEN 'Medical supplies'
    WHEN 'DT' THEN 'Dental' WHEN 'RR' THEN 'Reagents' WHEN 'SV' THEN 'Services' WHEN 'NM' THEN 'Non-medical'
    WHEN 'ME' THEN 'Medical equipment' WHEN 'SP' THEN 'Spare parts' WHEN 'ZA' THEN 'Other'
    WHEN NULL THEN 'Not set' ELSE COALESCE(NULLIF(LTRIM(RTRIM({c})), ''), 'Not set') END"""

# ---------------------------------------------------------------- shared: stock-flow chain
# grain: stage x warehouse. Count = the stage's figure; AgeDays = oldest waiting item; Flags = items that
# turn the stage to its flag tone. Tone (computed by the visual from SUM(Count), MAX(AgeDays), SUM(Flags)):
#   Count = 0 -> none; Flags > 0 -> FlagTone; AgeDays > AgeLimit -> watch; else BaseTone.
CHAIN = """
SELECT 'Inbound' AS Stage, 1 AS StageOrder, 'arriving' AS Unit, 'info' AS BaseTone, 'watch' AS FlagTone, 2 AS AgeLimit,
       'Not set' AS Warehouse,
       COUNT(*) AS [Count], MAX(DATEDIFF(day, CAST(g.ArrivalDate AS date), CAST(GETDATE() AS date))) AS AgeDays, 0 AS Flags
FROM pos.GAN g WHERE NOT EXISTS (SELECT 1 FROM pos.GRN r WHERE r.GANGuid = g.ID)
UNION ALL
SELECT 'Quality', 2, 'in QC', 'info', 'watch', 3, 'Not set',
       COUNT(*), MAX(DATEDIFF(day, CAST(q.RequestDate AS date), CAST(GETDATE() AS date))), 0
FROM veims.QualityControlRequest q WHERE q.QAStatus IN ('Pending', 'New', 'Open', 'In Progress')
UNION ALL
SELECT 'Receipt', 3, 'receipts', 'good', 'watch', NULL, """ + WH.format(a="w") + """,
       COUNT(*), NULL, SUM(CASE WHEN r.OnHold = 1 THEN 1 ELSE 0 END)
FROM pos.GRN r LEFT JOIN wms.WareHouse w ON w.ID = r.WareHouseGuid GROUP BY """ + WH.format(a="w") + """
UNION ALL
SELECT 'Put-away', 4, 'pending', 'good', 'watch', NULL, """ + WH.format(a="w") + """,
       SUM(CASE WHEN p.TaskCount > 0 AND p.CompletedTaskCount >= p.TaskCount THEN 0 ELSE 1 END), NULL,
       SUM(CASE WHEN p.TaskCount > 0 AND p.CompletedTaskCount >= p.TaskCount THEN 0 ELSE 1 END)
FROM wms.PutAwayConfirmation p LEFT JOIN wms.WareHouse w ON w.ID = p.WareHouseGuid GROUP BY """ + WH.format(a="w") + """
UNION ALL
SELECT 'Storage', 5, 'items', 'good', 'action', NULL, """ + WH.format(a="w") + """,
       COUNT(DISTINCT s.ItemGuid), NULL,
       (SELECT COUNT(*) FROM wms.SKUBatch b WHERE b.QtyOnHand > 0 AND b.ExpDate < CAST(GETDATE() AS date)
          AND EXISTS (SELECT 1 FROM wms.StockOnHand o WHERE o.BatchGuid = b.ID AND o.WareHouseGuid = s.WareHouseGuid AND o.QtyOnHand > 0))
FROM wms.StockOnHand s LEFT JOIN wms.WareHouse w ON w.ID = s.WareHouseGuid
WHERE s.QtyAvailable > 0 GROUP BY """ + WH.format(a="w") + """, s.WareHouseGuid
UNION ALL
SELECT 'Pick & pack', 6, 'requests', 'info', 'watch', NULL, """ + WH.format(a="w") + """,
       COUNT(*), NULL, 0
FROM veims.MaterialRequest r LEFT JOIN wms.WareHouse w ON w.ID = r.WareHouseGuid
WHERE r.VoucherStatus NOT IN ('Closed', 'Completed', 'Cancelled', 'Issued', 'Rejected') GROUP BY """ + WH.format(a="w") + """
UNION ALL
SELECT 'Dispatch', 7, 'dispatched', 'good', 'watch', NULL, 'Not set',
       SUM(CASE WHEN d.Shipped = 1 THEN 1 ELSE 0 END), NULL,
       SUM(CASE WHEN d.EstimatedDeliveryDate IS NOT NULL AND (
             (d.ActualDeliveryDate IS NULL AND d.EstimatedDeliveryDate < CAST(GETDATE() AS date))
          OR (d.ActualDeliveryDate > d.EstimatedDeliveryDate)) THEN 1 ELSE 0 END)
FROM vesos.DeliveryNote d
"""

# ---------------------------------------------------------------- W1 Stock & Expiry
# grain: batch on hand x warehouse that holds a stock line of it (a batch with no stock line: one row, 'Not set')
W1_BATCH = """
WITH b AS (
  SELECT b.ID AS BatchID, b.BatchNbr, b.ExpDate, b.QtyOnHand, i.ID AS ItemID, i.Description AS Item,
         """ + CATEGORY.format(c="i.ItemCategory") + """ AS Category,
         CASE WHEN i.Refrigeration = 1 OR i.StorageTemperature LIKE '%cold%' OR i.StorageRule LIKE '%cold%'
                   OR i.StorageTemperature LIKE '%2 to%' OR i.StorageRule LIKE '%2 to%'
                   OR i.StorageTemperature LIKE '%-15%' OR i.StorageRule LIKE '%-15%' THEN 'Cold chain'
              WHEN i.IsControlledSubstance = 1 THEN 'Controlled drugs'
              WHEN NULLIF(LTRIM(RTRIM(i.StorageTemperature)), '') IS NOT NULL
                OR NULLIF(LTRIM(RTRIM(i.StorageRule)), '') IS NOT NULL THEN 'Ambient'
              ELSE 'Not recorded' END AS StorageClass,
         DATEDIFF(day, CAST(GETDATE() AS date), b.ExpDate) AS DaysLeft
  FROM wms.SKUBatch b
  JOIN wms.SKU s          ON s.ID = b.SKUGuid
  JOIN veims.ItemMaster i ON i.ID = s.ItemGuid
  WHERE b.QtyOnHand > 0
)
SELECT CAST(b.BatchID AS varchar(36)) AS BatchID, b.BatchNbr, b.Item, b.Category, b.StorageClass, b.ExpDate,
       DATEFROMPARTS(YEAR(b.ExpDate), MONTH(b.ExpDate), 1) AS ExpiryMonth, b.DaysLeft, b.QtyOnHand,
       CASE WHEN b.ExpDate IS NULL THEN 'No expiry date' WHEN b.DaysLeft < 0 THEN 'Expired'
            WHEN b.DaysLeft <= 90 THEN N'≤ 90 d' WHEN b.DaysLeft <= 180 THEN N'91–180 d'
            WHEN b.DaysLeft <= 365 THEN N'181–365 d' ELSE '> 1 year' END AS [Window],
       CASE WHEN b.ExpDate IS NULL THEN 6 WHEN b.DaysLeft < 0 THEN 0 WHEN b.DaysLeft <= 90 THEN 1
            WHEN b.DaysLeft <= 180 THEN 2 WHEN b.DaysLeft <= 365 THEN 3 ELSE 4 END AS WindowOrder,
       """ + WH.format(a="w") + """ AS Warehouse
FROM b
LEFT JOIN (SELECT DISTINCT BatchGuid, WareHouseGuid FROM wms.StockOnHand WHERE QtyOnHand > 0) o ON o.BatchGuid = b.BatchID
LEFT JOIN wms.WareHouse w ON w.ID = o.WareHouseGuid
"""

# grain: one row per month, current month to the last expiry month (zero months included)
W1_MONTH = """
WITH r AS (
  SELECT DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1) AS m,
         (SELECT MAX(DATEFROMPARTS(YEAR(ExpDate), MONTH(ExpDate), 1)) FROM wms.SKUBatch WHERE QtyOnHand > 0) AS last_m
  UNION ALL SELECT DATEADD(month, 1, m), last_m FROM r WHERE m < last_m
)
SELECT m AS ExpiryMonth, FORMAT(m, 'MMM yy', 'en-GB') AS MonthLabel,
       CASE WHEN m <= DATEADD(day, 90, CAST(GETDATE() AS date)) THEN 1 ELSE 0 END AS InNext90Days
FROM r OPTION (MAXRECURSION 600)
"""

# grain: stock line (wms.StockOnHand row)
W1_STOCKLINE = """
SELECT CAST(s.ID AS varchar(36)) AS StockLineID, CAST(s.SKUGuid AS varchar(36)) AS SKUID, s.QtyOnHand,
       """ + CATEGORY.format(c="i.ItemCategory") + """ AS Category, """ + WH.format(a="w") + """ AS Warehouse
FROM wms.StockOnHand s
LEFT JOIN veims.ItemMaster i ON i.ID = s.ItemGuid
LEFT JOIN wms.WareHouse w ON w.ID = s.WareHouseGuid
"""

# grain: issued item + batch pair that broke FEFO (an older-expiring batch of the item was on hand)
W1_FEFO = """
WITH iss AS (
  SELECT DISTINCT w.ItemGuid, w.BatchNbr, w.BinLocationGuid FROM veims.ItemWithdrawals w WHERE w.BatchNbr IS NOT NULL
), x AS (
  SELECT iss.*, (SELECT MIN(b.ExpDate) FROM wms.SKUBatch b WHERE b.BatchNbr = iss.BatchNbr) AS BatchExp FROM iss
)
SELECT CAST(x.ItemGuid AS varchar(36)) + '|' + x.BatchNbr AS Pair, """ + CATEGORY.format(c="i.ItemCategory") + """ AS Category,
       """ + WH.format(a="wh") + """ AS Warehouse
FROM x
JOIN veims.ItemMaster i ON i.ID = x.ItemGuid
LEFT JOIN wms.BinLocation bl ON bl.ID = x.BinLocationGuid
LEFT JOIN wms.WareHouse wh ON wh.ID = bl.WareHouseGuid
WHERE x.BatchExp IS NOT NULL AND EXISTS (
  SELECT 1 FROM wms.SKUBatch b JOIN wms.SKU s ON s.ID = b.SKUGuid
  WHERE s.ItemGuid = x.ItemGuid AND b.QtyOnHand > 0 AND b.ExpDate < x.BatchExp)
"""

# ---------------------------------------------------------------- W4 Stock Accuracy & Control
# grain: physical count line
W4_COUNTLINE = """
SELECT CAST(i.ID AS varchar(36)) AS CountLineID, p.PhysicalInventoryId AS CountNo,
       COALESCE(NULLIF(LTRIM(RTRIM(p.PhysicalInventoryTitle)), ''), 'Count ' + CAST(p.PhysicalInventoryId AS varchar(20))) AS [Count],
       CAST(p.PhysicalInventoryDate AS date) AS CountDate, p.PhysicalInventoryStatus AS CountStatus,
       """ + WH.format(a="w") + """ AS Warehouse, CAST(i.ItemGuid AS varchar(36)) AS ItemID, m.Description AS Item,
       """ + CATEGORY.format(c="m.ItemCategory") + """ AS Category,
       i.OpeningQty AS OnHand, i.ClosingQty AS Counted, i.DifferenceQty AS Difference,
       CASE WHEN i.DifferenceQty = 0 THEN 'Exact' ELSE 'Variance' END AS Result,
       CASE WHEN i.DifferenceQty = 0 THEN NULL WHEN m.IsControlledSubstance = 1 THEN 'Controlled drug'
            WHEN i.DifferenceQty < 0 THEN 'Short' ELSE 'Over' END AS VarianceNote,
       CASE WHEN i.DifferenceQty = 0 THEN NULL WHEN m.IsControlledSubstance = 1 THEN 'action' ELSE 'watch' END AS VarianceTone
FROM veims.PhysicalInventoryItem i
LEFT JOIN veims.PhysicalInventory p ON p.ID = i.PhysicalInventoryGuid
LEFT JOIN wms.WareHouse w ON w.ID = p.WareHouseGuid
LEFT JOIN veims.ItemMaster m ON m.ID = i.ItemGuid
"""

# grain: item x warehouse with available stock; Counted = a count line exists for the item in that warehouse
W4_STOCKITEM = """
SELECT CAST(s.ItemGuid AS varchar(36)) AS ItemID, """ + WH.format(a="w") + """ AS Warehouse,
       CASE WHEN EXISTS (SELECT 1 FROM veims.PhysicalInventoryItem ci JOIN veims.PhysicalInventory cp ON cp.ID = ci.PhysicalInventoryGuid
                         WHERE ci.ItemGuid = s.ItemGuid AND cp.WareHouseGuid = s.WareHouseGuid) THEN 'Counted' ELSE 'Not yet counted' END AS Coverage
FROM (SELECT DISTINCT ItemGuid, WareHouseGuid FROM wms.StockOnHand WHERE QtyAvailable > 0) s
LEFT JOIN wms.WareHouse w ON w.ID = s.WareHouseGuid
"""

# grain: inventory movement
W4_MOVEMENT = """
SELECT CAST(m.MovementID AS varchar(36)) AS MovementID, CAST(m.MovementDate AS date) AS MovementDate,
       DATEFROMPARTS(YEAR(m.MovementDate), MONTH(m.MovementDate), 1) AS MovementMonth,
       CASE m.MovementType WHEN 'RECEIPT' THEN 'Receipt' WHEN 'PUTAWAY' THEN 'Put-away'
            WHEN 'TRANSFER-IN' THEN 'Transfer' WHEN 'TRANSFER-OUT' THEN 'Transfer'
            WHEN 'BIN-IN' THEN 'Bin move' WHEN 'BIN-OUT' THEN 'Bin move'
            WHEN 'ADJUST' THEN 'Adjust / staging' WHEN 'STAGING' THEN 'Adjust / staging'
            WHEN 'RETURN' THEN 'Return' WHEN 'RETURN-IN' THEN 'Return' WHEN 'RETURN-OUT' THEN 'Return'
            WHEN 'ISSUE' THEN 'Issue / quarantine' WHEN 'QUARANTINE' THEN 'Issue / quarantine' ELSE 'Other' END AS MovementGroup,
       """ + WH.format(a="w") + """ AS Warehouse
FROM wms.InventoryMovement m LEFT JOIN wms.WareHouse w ON w.ID = m.WareHouseGuid
"""

# grain: posted adjustment (wms.ExceptionLog row)
W4_ADJUSTMENT = """
SELECT CAST(a.ID AS varchar(36)) AS AdjustmentID, CAST(a.CreatedDTTM AS date) AS AdjustmentDate, a.AdjustmentQty,
       """ + WH.format(a="w") + """ AS Warehouse
FROM wms.ExceptionLog a LEFT JOIN wms.BinLocation bl ON bl.ID = a.BinLocationGuid LEFT JOIN wms.WareHouse w ON w.ID = bl.WareHouseGuid
"""

# ---------------------------------------------------------------- W7 Outbound & Transfers
# grain: material request
W7_REQUEST = """
SELECT CAST(r.ID AS varchar(36)) AS RequestID, r.VoucherNbr AS Request,
       COALESCE(NULLIF(LTRIM(RTRIM(r.VoucherType)), ''), 'Not set') AS RequestType,
       COALESCE(NULLIF(LTRIM(RTRIM(r.VoucherTitle)), ''), N'–') AS Reference,
       CAST(r.VoucherDate AS date) AS Raised, r.VoucherStatus AS RawStatus,
       CASE WHEN r.VoucherStatus IN ('Cancelled', 'Rejected') THEN 'Cancelled'
            WHEN r.VoucherStatus IN ('Closed', 'Completed', 'Issued') THEN 'Closed' ELSE 'Open' END AS Status,
       CASE WHEN r.VoucherStatus IN ('Cancelled', 'Rejected') THEN 3
            WHEN r.VoucherStatus IN ('Closed', 'Completed', 'Issued') THEN 2 ELSE 1 END AS StatusOrder,
       """ + WH.format(a="w") + """ AS Warehouse
FROM veims.MaterialRequest r LEFT JOIN wms.WareHouse w ON w.ID = r.WareHouseGuid
"""

# grain: item issue (veims.ItemWithdrawals row)
W7_ISSUE = """
SELECT CAST(x.ID AS varchar(36)) AS IssueID, CAST(x.WithDrawalDate AS date) AS IssueDate, x.WithDrawalQty AS Qty,
       COALESCE(NULLIF(LTRIM(RTRIM(mr.VoucherType)), ''), 'Not set') AS RequestType,
       """ + WH.format(a="w") + """ AS Warehouse
FROM veims.ItemWithdrawals x
LEFT JOIN veims.MaterialRequest mr ON mr.ID = x.MaterialRequestGuid
LEFT JOIN wms.BinLocation bl ON bl.ID = x.BinLocationGuid
LEFT JOIN wms.WareHouse w ON w.ID = COALESCE(bl.WareHouseGuid, mr.WareHouseGuid)
"""

# grain: stock transfer order
W7_TRANSFER = """
SELECT CAST(o.ID AS varchar(36)) AS TransferID, o.StockTransferOrderID AS Transfer, CAST(o.StockTransferOrderDate AS date) AS OrderDate,
       o.StockTransferOrderStatus AS Status,
       CASE WHEN EXISTS (SELECT 1 FROM veims.StockTransferDelivery d WHERE d.StockTransferOrderGuid = o.ID)
             AND NOT EXISTS (SELECT 1 FROM veims.StockTransferReceiving r WHERE r.StockTransferOrderGuid = o.ID) THEN 1 ELSE 0 END AS InTransit,
       CASE WHEN o.DeliveryDueDate IS NOT NULL AND o.DeliveryDueDate < CAST(GETDATE() AS date)
             AND NOT EXISTS (SELECT 1 FROM veims.StockTransferReceiving r WHERE r.StockTransferOrderGuid = o.ID) THEN 1 ELSE 0 END AS Late,
       """ + WH.format(a="w") + """ AS Warehouse
FROM veims.StockTransferOrder o LEFT JOIN wms.WareHouse w ON w.ID = o.WareHouseGuid
"""

# grain: delivery note
W7_DELIVERY = """
SELECT CAST(d.ID AS varchar(36)) AS DeliveryID, d.DeliveryNoteNum AS Delivery, CAST(d.DeliveryNoteDate AS date) AS NoteDate,
       d.DeliveryNoteStatus AS Status, CASE WHEN d.Shipped = 1 THEN 1 ELSE 0 END AS Shipped,
       CASE WHEN d.ActualDeliveryDate IS NOT NULL AND d.EstimatedDeliveryDate IS NOT NULL
             AND d.ActualDeliveryDate <= d.EstimatedDeliveryDate THEN 1 ELSE 0 END AS OnTime,
       CASE WHEN d.EstimatedDeliveryDate IS NOT NULL AND (
             (d.ActualDeliveryDate IS NULL AND d.EstimatedDeliveryDate < CAST(GETDATE() AS date))
          OR (d.ActualDeliveryDate > d.EstimatedDeliveryDate)) THEN 1 ELSE 0 END AS Late,
       """ + WH.format(a="w") + """ AS Warehouse
FROM vesos.DeliveryNote d
LEFT JOIN wms.WareHouse w ON w.ID = (SELECT MIN(l.WarehouseGuid) FROM vesos.DeliveryNoteLine l WHERE l.DeliveryNoteGuid = d.ID)
"""

QUERIES = {
    "Chain": CHAIN,
    "W1.Batch": W1_BATCH, "W1.Month": W1_MONTH, "W1.StockLine": W1_STOCKLINE, "W1.FEFO": W1_FEFO,
    "W4.CountLine": W4_COUNTLINE, "W4.StockItem": W4_STOCKITEM, "W4.Movement": W4_MOVEMENT, "W4.Adjustment": W4_ADJUSTMENT,
    "W7.Request": W7_REQUEST, "W7.Issue": W7_ISSUE, "W7.Transfer": W7_TRANSFER, "W7.Delivery": W7_DELIVERY,
}

# ---------------------------------------------------------------- shared dimensions (live mode)
# Every value a fact can carry, plus 'Not set', so each relationship finds its row.
DIM_QUERIES = {
    "Warehouse": "SELECT DISTINCT " + WH.format(a="w") + " AS Warehouse FROM wms.WareHouse w UNION SELECT 'Not set'",
    "Category": "SELECT DISTINCT " + CATEGORY.format(c="i.ItemCategory") + " AS Category FROM veims.ItemMaster i UNION SELECT 'Not set'",
    "RequestType": "SELECT DISTINCT COALESCE(NULLIF(LTRIM(RTRIM(r.VoucherType)), ''), 'Not set') AS RequestType "
    "FROM veims.MaterialRequest r UNION SELECT 'Not set'",
}
