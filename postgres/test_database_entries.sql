
-- 1. Check sub_industry values for Automotive policies
SELECT policy_name, sub_industry, business_size 
FROM policies 
WHERE industry ILIKE '%Automotive%';

-- 2. Check if 'EV Battery Manufacturing' exists exactly
SELECT COUNT(*) FROM policies 
WHERE sub_industry ILIKE '%EV Battery Manufacturing%';

-- 3. Check if 'Charging Infrastructure' exists exactly  
SELECT COUNT(*) FROM policies 
WHERE sub_industry ILIKE '%Charging Infrastructure%';

-- 4. Check if 'Medical Electronics' exists exactly
SELECT COUNT(*) FROM policies 
WHERE sub_industry ILIKE '%Medical Electronics%';

SELECT 
    COUNT(*) FILTER (WHERE sub_industry ILIKE '%EV Battery Manufacturing%') AS ev_battery,
    COUNT(*) FILTER (WHERE sub_industry ILIKE '%Charging Infrastructure%')  AS charging,
    COUNT(*) FILTER (WHERE sub_industry ILIKE '%Medical Electronics%')      AS medical,
    COUNT(*) FILTER (WHERE sub_industry IS NULL)                            AS null_sub_industry,
    COUNT(*) FILTER (WHERE sub_industry = '')                               AS empty_sub_industry
FROM policies;