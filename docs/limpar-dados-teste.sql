-- limpar-dados-teste.sql
-- Zera TODAS as tabelas de dados e MANTÉM apenas a `usuarios`.
--
-- ⚠️  DESTRUTIVO E IRREVERSÍVEL. Em produção, FAÇA BACKUP ANTES:
--        sudo -u postgres pg_dump gestao_servpen > ~/backup_antes.sql
--
-- MANTÉM:  usuarios  (todos os usuários cadastrados ficam intactos)
-- APAGA:   agenda, arquivos, auditoria, chat, diario, diario_leituras,
--          etapas_projeto, login_falhas, mencoes_acesso,
--          mencoes_notificacoes, progresso_disciplinas, projetos, sessoes
--
-- Observações:
--   • `sessoes` zerada = todos os logins ativos caem; cada um entra de
--     novo (inclusive você). Inofensivo, só re-loga.
--   • `login_falhas` zerada = reseta contadores de tentativa (rate-limit).
--   • `auditoria` zerada = apaga o histórico de ações (log). Se quiser
--     PRESERVAR o log, remova "auditoria," da lista abaixo.
--   • RESTART IDENTITY zera os contadores de id (próximo projeto = 1).
--   • CASCADE cobre as foreign keys (ex.: etapas_projeto → projetos).

BEGIN;

TRUNCATE TABLE
    progresso_disciplinas,
    etapas_projeto,
    diario_leituras,
    diario,
    arquivos,
    agenda,
    chat,
    mencoes_notificacoes,
    mencoes_acesso,
    projetos,
    auditoria,
    login_falhas,
    sessoes
RESTART IDENTITY CASCADE;

COMMIT;

-- Confere: usuarios deve continuar com gente; o resto zerado.
SELECT 'usuarios' AS tabela, COUNT(*) FROM usuarios
UNION ALL SELECT 'projetos', COUNT(*) FROM projetos
UNION ALL SELECT 'chat',     COUNT(*) FROM chat
UNION ALL SELECT 'agenda',   COUNT(*) FROM agenda
UNION ALL SELECT 'diario',   COUNT(*) FROM diario;
