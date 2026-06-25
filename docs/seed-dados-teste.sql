-- ════════════════════════════════════════════════════════════════════════
--  seed-dados-teste.sql — Usuários fake + dados COERENTES (projetos, diário,
--  tarefas) para teste/demonstração. Contexto: engenharia ServPen/UERJ.
--
--  Senha de TODOS os usuários:  Teste@123456
--    (hash SHA-256; o app valida e migra pra bcrypt no 1º login de cada um)
--
--  É IDEMPOTENTE: pode rodar de novo que ele limpa o que criou antes e recria.
--  Roda de uma vez. Usuários são preservados (ON CONFLICT) pra não resetar a
--  migração de senha; projetos/diário/tarefas do seed são recriados.
--
--  COMO RODAR (no PC com o container Docker):
--    docker exec -i gestao-postgres-local \
--      psql -U gestao_servpen -d gestao_servpen < docs/seed-dados-teste.sql
--
--  COMO REMOVER tudo depois (no fim do arquivo, bloco comentado).
-- ════════════════════════════════════════════════════════════════════════

SET client_encoding = 'UTF8';

BEGIN;

-- ── Limpa o seed anterior (idempotência) ────────────────────────────────
DELETE FROM diario  WHERE projeto_id IN (SELECT id FROM projetos
                                         WHERE codigo LIKE 'SP-2026-%');
DELETE FROM progresso_disciplinas WHERE projeto_id IN (SELECT id FROM projetos
                                         WHERE codigo LIKE 'SP-2026-%');
DELETE FROM etapas_projeto WHERE projeto_id IN (SELECT id FROM projetos
                                         WHERE codigo LIKE 'SP-2026-%');
DELETE FROM tarefas WHERE usuario IN
  ('Marcos Andrade','Carla Ribeiro','João Mendes','Patrícia Souza',
   'Rafael Lima','Beatriz Costa')
  OR criado_por IN
  ('Marcos Andrade','Carla Ribeiro','João Mendes','Patrícia Souza',
   'Rafael Lima','Beatriz Costa');
DELETE FROM projetos WHERE codigo LIKE 'SP-2026-%';
DELETE FROM agenda WHERE titulo IN (
  'Reunião de abertura - Reforma Elétrica',
  'Visita técnica - Pavilhão João Lyra Filho',
  'Reunião de cronograma (sexta)',
  'Folga - Rafael Lima',
  'Visita técnica - CFTV Campus',
  'Apresentação do projeto HVAC',
  'Férias - João Mendes');
DELETE FROM chat WHERE remetente IN
  ('Marcos Andrade','Carla Ribeiro','João Mendes','Patrícia Souza',
   'Rafael Lima','Beatriz Costa')
  OR destinatario IN
  ('Marcos Andrade','Carla Ribeiro','João Mendes','Patrícia Souza',
   'Rafael Lima','Beatriz Costa');

-- ── USUÁRIOS (senha = Teste@123456) ─────────────────────────────────────
INSERT INTO usuarios (nome, senha, perfil, cargo, equipe) VALUES
 ('Marcos Andrade', 'd09ab6fa23a7b973ee933145fc8573ed96b55edf6934f8bd8d9ea6fe159a3f84', 'Gestor',       'Coordenador de Projetos',  'GERAL'),
 ('Carla Ribeiro',  'd09ab6fa23a7b973ee933145fc8573ed96b55edf6934f8bd8d9ea6fe159a3f84', 'Projetista',   'Engenheira Eletricista',   'SERVPEN'),
 ('João Mendes',    'd09ab6fa23a7b973ee933145fc8573ed96b55edf6934f8bd8d9ea6fe159a3f84', 'Projetista',   'Engenheiro Civil',         'SERVPEN'),
 ('Patrícia Souza', 'd09ab6fa23a7b973ee933145fc8573ed96b55edf6934f8bd8d9ea6fe159a3f84', 'Projetista',   'Engenheira Mecânica',      'SERVPAR'),
 ('Rafael Lima',    'd09ab6fa23a7b973ee933145fc8573ed96b55edf6934f8bd8d9ea6fe159a3f84', 'Projetista',   'Técnico em CFTV',          'SERVPAR'),
 ('Beatriz Costa',  'd09ab6fa23a7b973ee933145fc8573ed96b55edf6934f8bd8d9ea6fe159a3f84', 'Visualizador', 'Estagiária de Engenharia', 'SERVPEN')
ON CONFLICT (nome) DO NOTHING;

-- ── PROJETOS ────────────────────────────────────────────────────────────
INSERT INTO projetos
  (codigo, projeto, projetista, endereco, local, solicitante, contato,
   numero_sei, status, prioridade, data_recebimento, previsao_execucao,
   data_inicio, data_termino, demandas, solicitacao)
VALUES
 ('SP-2026-001', 'Reforma Elétrica - Pavilhão João Lyra Filho', 'Carla Ribeiro',
  'Rua São Francisco Xavier, 524 - Maracanã', 'Pavilhão João Lyra Filho, 5º andar',
  'Diretoria do CTC', '(21) 2334-0101', 'SEI-260001/2026', 'Ativo', 'Máxima',
  DATE '2026-05-10', DATE '2026-06-30', DATE '2026-06-02', NULL, 'Elétrica, SPDA',
  'Adequação da rede elétrica e dos quadros do pavilhão à nova carga dos laboratórios.'),
 ('SP-2026-002', 'Sistema CFTV - Campus Maracanã', 'Rafael Lima',
  'Rua São Francisco Xavier, 524 - Maracanã', 'Campus Maracanã, blocos A e B',
  'Prefeitura do Campus', '(21) 2334-0202', 'SEI-260002/2026', 'Ativo', 'Média',
  DATE '2026-05-15', DATE '2026-07-10', DATE '2026-06-04', NULL, 'CFTV',
  'Implantação de CFTV IP com 48 câmeras nos acessos e corredores principais.'),
 ('SP-2026-003', 'Climatização HVAC - Biblioteca CTC', 'Patrícia Souza',
  'Rua São Francisco Xavier, 524 - Maracanã', 'Biblioteca do CTC, 2º pavimento',
  'Direção da Biblioteca', '(21) 2334-0303', 'SEI-260003/2026', 'Ativo', 'Média',
  DATE '2026-06-01', DATE '2026-08-01', NULL, NULL, 'HVAC',
  'Projeto de climatização das salas de estudo com sistema VRF.'),
 ('SP-2026-004', 'Adequação Hidráulica - Laboratórios IBRAG', 'João Mendes',
  'Rua São Francisco Xavier, 524 - Maracanã', 'Laboratórios do IBRAG, térreo',
  'Coordenação do IBRAG', '(21) 2334-0404', 'SEI-260004/2026', 'Em Espera', 'Mínima',
  DATE '2026-06-05', DATE '2026-09-01', NULL, NULL, 'Hidráulica',
  'Adequação das instalações hidráulicas e prumadas dos laboratórios.'),
 ('SP-2026-005', 'Projeto SPDA - Bloco F', 'Carla Ribeiro',
  'Rua São Francisco Xavier, 524 - Maracanã', 'Bloco F, cobertura',
  'Prefeitura do Campus', '(21) 2334-0505', 'SEI-260005/2026', 'Concluído', 'Média',
  DATE '2026-04-01', DATE '2026-05-20', DATE '2026-04-10', DATE '2026-05-20', 'SPDA',
  'Projeto e instalação do SPDA do Bloco F.'),
 ('SP-2026-006', 'Reforma do Telhado - Bloco D', 'João Mendes',
  'Rua São Francisco Xavier, 524 - Maracanã', 'Bloco D, cobertura',
  'Prefeitura do Campus', '(21) 2334-0606', 'SEI-260006/2026', '🛑 Parado', 'Mínima',
  DATE '2026-03-15', NULL, NULL, NULL, 'Civil',
  'Substituição da estrutura e telhas do Bloco D. Parado aguardando liberação de verba.'),
 ('SP-2026-007', 'Modernização de Elevadores - Pavilhão', 'Patrícia Souza',
  'Rua São Francisco Xavier, 524 - Maracanã', 'Pavilhão João Lyra Filho, todos os andares',
  'Diretoria do CTC', '(21) 2334-0707', 'SEI-260007/2026', 'Cancelado', 'Média',
  DATE '2026-02-10', NULL, NULL, NULL, 'Mecânica',
  'Modernização dos elevadores cancelada por reformulação do orçamento anual.');

-- ── ETAPAS DO PROJETO (alimentam o Gantt PDF e a seção "Etapas") ───────
INSERT INTO etapas_projeto
  (projeto_id, ordem, nome, dias_offset, duracao_dias, percentual)
VALUES
 ((SELECT id FROM projetos WHERE codigo='SP-2026-001'), 0, 'Levantamento de cargas', 0, 5, 100),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-001'), 1, 'Projeto dos quadros', 5, 10, 100),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-001'), 2, 'Compra de materiais', 15, 7, 50),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-001'), 3, 'Execução e ligações', 22, 15, 10),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-001'), 4, 'Testes e comissionamento', 37, 5, 0),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-002'), 0, 'Projeto de pontos', 0, 5, 100),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-002'), 1, 'Infraestrutura de eletrocalhas', 5, 12, 60),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-002'), 2, 'Cabeamento estruturado', 17, 10, 20),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-002'), 3, 'Instalação das câmeras', 27, 8, 0),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-002'), 4, 'Configuração do servidor', 35, 4, 0),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-003'), 0, 'Cálculo de carga térmica', 0, 6, 100),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-003'), 1, 'Projeto da rede de dutos', 6, 10, 30),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-003'), 2, 'Especificação dos equipamentos', 16, 5, 0),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-005'), 0, 'Projeto SPDA', 0, 7, 100),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-005'), 1, 'Instalação de captores e descidas', 7, 10, 100),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-005'), 2, 'Medição de aterramento', 17, 3, 100);

-- ── PROGRESSO POR DISCIPLINA (Evolução Técnica + barras no Dashboard) ──
INSERT INTO progresso_disciplinas
  (projeto_id, disciplina, concluido, percentual)
VALUES
 ((SELECT id FROM projetos WHERE codigo='SP-2026-001'), 'Elétrica', 0, 55),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-001'), 'SPDA', 0, 20),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-002'), 'CFTV', 0, 40),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-003'), 'HVAC', 0, 30),
 ((SELECT id FROM projetos WHERE codigo='SP-2026-005'), 'SPDA', 1, 100);

-- ── DIÁRIO (relatos, dúvidas, impedimentos + interações do gestor) ──────
-- A `resposta_gestor` traz interações no formato "[data] Autor (Perfil): texto"
-- separadas por quebra de linha → aparecem como BALÕES separados na aba Diário.
INSERT INTO diario
  (projeto_id, data, executado, autor, disciplina, horas, resolvido,
   resposta_gestor)
VALUES
 ((SELECT id FROM projetos WHERE codigo='SP-2026-001'), '02/06/2026 09:15',
  '[Relato de Atividade] Levantamento de cargas dos laboratórios do 5º andar concluído. Carga total estimada em 138 kVA, acima da capacidade do quadro atual.',
  'Carla Ribeiro', 'Elétrica', 4.0, 1,
  E'[02/06/2026 11:30] Marcos Andrade (Gestor): Ótimo levantamento. Pode seguir para o dimensionamento dos condutores.\n[02/06/2026 14:10] Carla Ribeiro (Projetista): Combinado, inicio o dimensionamento ainda hoje.'),

 ((SELECT id FROM projetos WHERE codigo='SP-2026-001'), '03/06/2026 08:40',
  '[❓ Dúvida Técnica] O quadro QDF atual suporta a nova carga dos laboratórios ou será necessário trocar o disjuntor geral?',
  'Carla Ribeiro', 'Elétrica', 1.0, 1,
  E'[03/06/2026 09:00] Marcos Andrade (Gestor): O QDF atual é de 100A. Com a nova carga vamos para 150A, então troque o disjuntor geral e os cabos de alimentação.\n[03/06/2026 09:45] Carla Ribeiro (Projetista): Entendido. Especifico disjuntor de 150A e cabo de 50mm2.'),

 ((SELECT id FROM projetos WHERE codigo='SP-2026-001'), '04/06/2026 15:50',
  '[🛑 Impedimento] Não é possível desligar o circuito principal em horário comercial. Preciso de autorização para trabalho no fim de semana.',
  'Carla Ribeiro', 'Elétrica', 0.5, 0,
  E'[04/06/2026 16:20] Marcos Andrade (Gestor): Vou solicitar a autorização de desligamento à prefeitura do campus. Aguarde retorno até segunda.'),

 ((SELECT id FROM projetos WHERE codigo='SP-2026-002'), '05/06/2026 10:00',
  '[❓ Dúvida Técnica] Qual modelo de câmera devo especificar para as áreas externas expostas à chuva?',
  'Rafael Lima', 'CFTV', 0.5, 1,
  E'[05/06/2026 10:15] Marcos Andrade (Gestor): Para área externa use câmeras bullet IP67 com IR de 30m. Padronize com o modelo já usado no Bloco B.\n[05/06/2026 10:40] Rafael Lima (Projetista): Perfeito, atualizo a lista de materiais.'),

 ((SELECT id FROM projetos WHERE codigo='SP-2026-002'), '05/06/2026 18:00',
  '[Relato de Atividade] Passagem de cabeamento UTP cat6 concluída no 2º pavimento. 24 pontos lançados até o rack do andar.',
  'Rafael Lima', 'CFTV', 6.0, 0, NULL),

 ((SELECT id FROM projetos WHERE codigo='SP-2026-002'), '06/06/2026 08:10',
  '[🛑 Impedimento] A eletrocalha do corredor principal ainda não foi instalada pela obra civil, bloqueando a passagem dos cabos.',
  'Rafael Lima', 'CFTV', 0.5, 0,
  E'[06/06/2026 08:30] Marcos Andrade (Gestor): A eletrocalha entra na próxima etapa da obra civil. Replaneje a passagem de cabos para depois do dia 15.'),

 ((SELECT id FROM projetos WHERE codigo='SP-2026-003'), '08/06/2026 14:30',
  '[Relato de Atividade] Cálculo de carga térmica das 6 salas concluído. Demanda total de 18 TR. Definida solução com sistema VRF.',
  'Patrícia Souza', 'HVAC', 5.0, 1, NULL),

 ((SELECT id FROM projetos WHERE codigo='SP-2026-003'), '09/06/2026 11:00',
  '[Relato de Atividade] Locação dos pontos de dreno e definição do caimento das tubulações de condensado.',
  'Patrícia Souza', 'HVAC', 3.0, 0, NULL),

 ((SELECT id FROM projetos WHERE codigo='SP-2026-004'), '09/06/2026 09:30',
  '[Relato de Atividade] Vistoria inicial das prumadas hidráulicas. Identificados 3 trechos com corrosão aparente.',
  'João Mendes', 'Hidráulica', 4.0, 0, NULL),

 ((SELECT id FROM projetos WHERE codigo='SP-2026-004'), '10/06/2026 14:20',
  '[❓ Dúvida Técnica] Posso reaproveitar a tubulação de água fria existente ou é mais seguro substituir todo o trecho?',
  'João Mendes', 'Hidráulica', 0.5, 0,
  E'[10/06/2026 15:00] Marcos Andrade (Gestor): Só reaproveite se o ensaio de estanqueidade passar. Caso contrário, substitua o trecho.'),

 ((SELECT id FROM projetos WHERE codigo='SP-2026-005'), '19/05/2026 16:00',
  '[Relato de Atividade] Medição da resistência de aterramento do SPDA: 8 ohms, dentro do limite normativo de 10 ohms.',
  'Carla Ribeiro', 'SPDA', 3.0, 1, NULL),

 ((SELECT id FROM projetos WHERE codigo='SP-2026-005'), '20/05/2026 16:30',
  '[Relato de Atividade] Instalação dos captores Franklin e descidas concluída. Sistema pronto para inspeção final.',
  'Carla Ribeiro', 'SPDA', 6.0, 1,
  E'[20/05/2026 17:00] Marcos Andrade (Gestor): Excelente, projeto dentro da norma. Pode encaminhar para emissão da ART.');

-- ── TAREFAS (cobre: própria, atrasada ⏰, recorrente 🔁, privada 🔒,
--    concluída, vinculada a projeto 📁 e ATRIBUÍDA pelo gestor) ───────────
INSERT INTO tarefas
  (usuario, descricao, concluida, privada, criado_por, equipe, data, vista,
   projeto_id, recorrencia, concluida_em)
VALUES
 ('Carla Ribeiro', 'Revisar memorial de cálculo do QDF', 0, 0, 'Carla Ribeiro',
  'SERVPEN', DATE '2026-06-25', 1,
  (SELECT id FROM projetos WHERE codigo='SP-2026-001'), 'nenhuma', NULL),
 ('Carla Ribeiro', 'Enviar ART ao CREA', 0, 0, 'Carla Ribeiro',
  'SERVPEN', DATE '2026-06-18', 1, NULL, 'nenhuma', NULL),
 ('Carla Ribeiro', 'Backup semanal dos arquivos do projeto', 0, 0,
  'Carla Ribeiro', 'SERVPEN', DATE '2026-06-25', 1, NULL, 'semanal', NULL),
 ('Carla Ribeiro', 'Imprimir plantas em A1 para a obra', 1, 0, 'Carla Ribeiro',
  'SERVPEN', DATE '2026-06-20', 1,
  (SELECT id FROM projetos WHERE codigo='SP-2026-001'), 'nenhuma',
  TIMESTAMP '2026-06-20 17:00:00'),
 ('Rafael Lima', 'Testar a gravação das câmeras do 2º pavimento', 0, 0,
  'Rafael Lima', 'SERVPAR', DATE '2026-06-25', 1,
  (SELECT id FROM projetos WHERE codigo='SP-2026-002'), 'nenhuma', NULL),
 ('Rafael Lima', 'Estudar requisitos da NBR para CFTV', 0, 1, 'Rafael Lima',
  'SERVPAR', DATE '2026-06-26', 1, NULL, 'nenhuma', NULL),
 ('João Mendes', 'Refazer o isométrico do banheiro do 3º andar', 0, 0,
  'João Mendes', 'SERVPEN', DATE '2026-06-15', 1, NULL, 'nenhuma', NULL),
 ('Patrícia Souza', 'Selecionar os fancoils das salas de aula', 0, 0,
  'Patrícia Souza', 'SERVPAR', DATE '2026-06-27', 1,
  (SELECT id FROM projetos WHERE codigo='SP-2026-003'), 'nenhuma', NULL),
 ('João Mendes', 'Atualizar a planta hidráulica com as revisões da vistoria',
  0, 0, 'Marcos Andrade', 'SERVPEN', DATE '2026-06-25', 0,
  (SELECT id FROM projetos WHERE codigo='SP-2026-004'), 'nenhuma', NULL),
 ('Carla Ribeiro', 'Apresentar o cronograma na reunião de sexta', 0, 0,
  'Marcos Andrade', 'SERVPEN', DATE '2026-06-27', 0, NULL, 'nenhuma', NULL);

-- ── AGENDA (eventos coerentes; o 1º é HOJE p/ disparar o aviso do dia) ──
INSERT INTO agenda
  (titulo, tipo, data_inicio, data_fim, responsaveis, descricao, local)
VALUES
 ('Reunião de abertura - Reforma Elétrica', 'Reunião',
  DATE '2026-06-25', DATE '2026-06-25', 'Marcos Andrade, Carla Ribeiro',
  'Kickoff da obra elétrica do pavilhão.', 'Sala de reuniões da ServPen'),
 ('Visita técnica - Pavilhão João Lyra Filho', 'Visita Técnica',
  DATE '2026-06-26', DATE '2026-06-26', 'Carla Ribeiro, Marcos Andrade',
  'Vistoria dos quadros elétricos antes da intervenção.',
  'Pavilhão João Lyra Filho, 5º andar'),
 ('Reunião de cronograma (sexta)', 'Reunião',
  DATE '2026-06-27', DATE '2026-06-27',
  'Marcos Andrade, Carla Ribeiro, Rafael Lima, Patrícia Souza',
  'Alinhamento do cronograma dos projetos em execução.',
  'Sala de reuniões da ServPen'),
 ('Folga - Rafael Lima', 'Folga',
  DATE '2026-06-29', DATE '2026-06-29', 'Rafael Lima',
  'Compensação de horas.', ''),
 ('Visita técnica - CFTV Campus', 'Visita Técnica',
  DATE '2026-06-30', DATE '2026-06-30', 'Rafael Lima',
  'Conferência das eletrocalhas e dos pontos de câmera.',
  'Campus Maracanã, blocos A e B'),
 ('Apresentação do projeto HVAC', 'Reunião',
  DATE '2026-07-03', DATE '2026-07-03', 'Patrícia Souza, Marcos Andrade',
  'Apresentação da solução VRF para a direção da biblioteca.',
  'Biblioteca do CTC'),
 ('Férias - João Mendes', 'Férias',
  DATE '2026-07-07', DATE '2026-07-18', 'João Mendes',
  'Férias programadas.', '');

-- ── CHAT (grupos @grupo:* + diretas; ficam como NÃO LIDAS → badges) ─────
INSERT INTO chat (remetente, destinatario, mensagem, data) VALUES
 ('Marcos Andrade', '@grupo:TODOS',
  'Pessoal, reunião de cronograma na sexta às 10h. Confirmem presença.',
  '24/06/2026 09:00'),
 ('Carla Ribeiro', '@grupo:TODOS', 'Confirmado!', '24/06/2026 09:05'),
 ('Rafael Lima', '@grupo:TODOS', 'Presença confirmada.', '24/06/2026 09:12'),
 ('Marcos Andrade', '@grupo:SERVPEN',
  'Carla e João, prioridade total na Reforma Elétrica esta semana.',
  '24/06/2026 14:00'),
 ('Carla Ribeiro', '@grupo:SERVPEN', 'Ok, o memorial do QDF sai hoje.',
  '24/06/2026 14:10'),
 ('Marcos Andrade', '@grupo:SERVPAR',
  'Patrícia e Rafael, foco no levantamento de campo dos dois projetos.',
  '24/06/2026 15:00'),
 ('Rafael Lima', '@grupo:SERVPAR', 'Combinado.', '24/06/2026 15:03'),
 ('Marcos Andrade', 'Carla Ribeiro',
  'Carla, conseguiu a autorização de desligamento do circuito?',
  '24/06/2026 16:00'),
 ('Carla Ribeiro', 'Marcos Andrade',
  'Ainda não, a prefeitura do campus retorna na segunda.',
  '24/06/2026 16:20'),
 ('João Mendes', 'Carla Ribeiro',
  'Carla, me passa o contato do fornecedor de cabos quando puder?',
  '24/06/2026 17:00');

COMMIT;

-- ════════════════════════════════════════════════════════════════════════
--  PARA REMOVER todo o seed depois (rode este bloco):
--
--  BEGIN;
--  DELETE FROM diario  WHERE projeto_id IN (SELECT id FROM projetos
--                                           WHERE codigo LIKE 'SP-2026-%');
--  DELETE FROM tarefas WHERE usuario IN
--    ('Marcos Andrade','Carla Ribeiro','João Mendes','Patrícia Souza',
--     'Rafael Lima','Beatriz Costa')
--    OR criado_por IN
--    ('Marcos Andrade','Carla Ribeiro','João Mendes','Patrícia Souza',
--     'Rafael Lima','Beatriz Costa');
--  DELETE FROM progresso_disciplinas WHERE projeto_id IN
--    (SELECT id FROM projetos WHERE codigo LIKE 'SP-2026-%');
--  DELETE FROM etapas_projeto WHERE projeto_id IN
--    (SELECT id FROM projetos WHERE codigo LIKE 'SP-2026-%');
--  DELETE FROM projetos WHERE codigo LIKE 'SP-2026-%';
--  DELETE FROM agenda WHERE titulo IN
--    ('Reunião de abertura - Reforma Elétrica',
--     'Visita técnica - Pavilhão João Lyra Filho',
--     'Reunião de cronograma (sexta)','Folga - Rafael Lima',
--     'Visita técnica - CFTV Campus','Apresentação do projeto HVAC',
--     'Férias - João Mendes');
--  DELETE FROM chat WHERE remetente IN
--    ('Marcos Andrade','Carla Ribeiro','João Mendes','Patrícia Souza',
--     'Rafael Lima','Beatriz Costa')
--    OR destinatario IN
--    ('Marcos Andrade','Carla Ribeiro','João Mendes','Patrícia Souza',
--     'Rafael Lima','Beatriz Costa');
--  DELETE FROM usuarios WHERE nome IN
--    ('Marcos Andrade','Carla Ribeiro','João Mendes','Patrícia Souza',
--     'Rafael Lima','Beatriz Costa');
--  COMMIT;
-- ════════════════════════════════════════════════════════════════════════
