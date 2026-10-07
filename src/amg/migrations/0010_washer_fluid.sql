-- Washer fluid joins the standard list, right after wiper blades. A top-up adds
-- fluid, so its usual action is replace, as for every other fluid. Skipped if
-- you already added a service of that name from /service-types: never two.
INSERT INTO service_types (code, name, category, powertrains, default_action, sort)
SELECT 'washer_fluid', 'Washer fluid', 'Electrical', 'gas,hybrid,ev', 'replace', 615
 WHERE NOT EXISTS (SELECT 1 FROM service_types WHERE name = 'Washer fluid' COLLATE NOCASE);

-- Receipt lines about washer fluid were confirmed with no service, because
-- there wasn't one, and learned wording wins over the reader's suggestion. Forget
-- only those, so the next such line gets the new service suggested; wording you
-- gave a service keeps it, and "drain plug washer" never says fluid.
DELETE FROM service_aliases
 WHERE covers_json = '[]'
   AND phrase LIKE '%fluid%'
   AND (phrase LIKE '%washer%' OR phrase LIKE '%wiper%' OR phrase LIKE '%windshield%' OR phrase LIKE '%windscreen%');
