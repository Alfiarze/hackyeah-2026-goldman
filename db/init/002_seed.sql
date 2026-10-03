INSERT INTO documents (path, client, label, title) VALUES
    ('/clients/A/contracts/acquisition.txt',          'A', 2, 'Share purchase agreement - Client A'),
    ('/clients/A/contracts/acquisition_injected.txt', 'A', 2, 'Share purchase agreement - Client A (vendor redline)'),
    ('/clients/B/contracts/nda.txt',                  'B', 2, 'NDA - Client B'),
    ('/public/templates/nda_template.txt',            NULL, 0, 'Public NDA template'),
    ('/clients/A/contracts/umowa-uslugi.pdf',         'A', 2, 'Umowa o usługi doradcze (PDF)'),
    ('/clients/A/contracts/umowa-od-kontrahenta.pdf', 'A', 2, 'Umowa od kontrahenta (PDF, metadane)'),
    ('/clients/A/contracts/umowa-od-kontrahenta.docx','A', 2, 'Umowa od kontrahenta (DOCX, ukryte części)')
ON CONFLICT (path) DO NOTHING;
