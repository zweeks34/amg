-- Wiper blades: few people keep the receipt for a pair of blades, so on a car
-- with none on record the wiper item counted every change since new as missed.
-- Start its count on the day this runs, as if the blades were changed then: the
-- server's date, which is the app's own "today". A car with something on record
-- that counts for the item (the rule of engine.schedule.meets) keeps counting
-- from it. A date you set yourself is kept, and a one-off item can't have one.
UPDATE schedule_items
   SET counts_from = date('now', 'localtime'),
       updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
 WHERE counts_from IS NULL
   AND (interval_miles IS NOT NULL OR interval_months IS NOT NULL)
   AND id IN (SELECT sis.schedule_item_id
                FROM schedule_item_services sis
                JOIN service_types st ON st.id = sis.service_type_id
               WHERE st.code = 'wiper_blades')
   AND NOT EXISTS (
        SELECT 1
          FROM service_events e
          JOIN line_items li ON li.service_event_id = e.id
          JOIN line_item_services lis ON lis.line_item_id = li.id
          JOIN service_types st ON st.id = lis.service_type_id
         WHERE e.vehicle_id = schedule_items.vehicle_id
           AND e.confirmed = 1
           AND ((lis.service_type_id IN (SELECT service_type_id FROM schedule_item_services
                                          WHERE schedule_item_id = schedule_items.id)
                 AND (schedule_items.action = 'inspect' OR lis.action IN ('replace', 'perform')))
                OR (schedule_items.action = 'inspect'
                    AND st.code IN ('multipoint_inspection', 'state_inspection'))));
