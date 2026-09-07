--
-- PostgreSQL database dump
--

\restrict Nvv7b8I3hAREHddo3NqRzNbtiDgRhP9JppeZBOXsPMgNNPkdlIDplT1DCdmPBMa

-- Dumped from database version 16.14
-- Dumped by pg_dump version 16.14

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: efdi_user
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO efdi_user;

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: efdi_user
--

CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    action character varying(50) NOT NULL,
    user_id integer,
    document_id integer,
    details jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.audit_logs OWNER TO efdi_user;

--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: efdi_user
--

CREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.audit_logs_id_seq OWNER TO efdi_user;

--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: efdi_user
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: classification_results; Type: TABLE; Schema: public; Owner: efdi_user
--

CREATE TABLE public.classification_results (
    id integer NOT NULL,
    document_id integer NOT NULL,
    predicted_type character varying(30) NOT NULL,
    confidence double precision NOT NULL,
    engine_name character varying(30) NOT NULL,
    signals jsonb NOT NULL,
    scores_by_type jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.classification_results OWNER TO efdi_user;

--
-- Name: classification_results_id_seq; Type: SEQUENCE; Schema: public; Owner: efdi_user
--

CREATE SEQUENCE public.classification_results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.classification_results_id_seq OWNER TO efdi_user;

--
-- Name: classification_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: efdi_user
--

ALTER SEQUENCE public.classification_results_id_seq OWNED BY public.classification_results.id;


--
-- Name: documents; Type: TABLE; Schema: public; Owner: efdi_user
--

CREATE TABLE public.documents (
    id integer NOT NULL,
    original_filename character varying(255) NOT NULL,
    stored_filename character varying(255) NOT NULL,
    document_type character varying(30) NOT NULL,
    status character varying(30) NOT NULL,
    file_size_bytes bigint NOT NULL,
    mime_type character varying(100) NOT NULL,
    file_hash character varying(64) NOT NULL,
    page_count integer,
    is_deleted boolean NOT NULL,
    uploaded_by integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.documents OWNER TO efdi_user;

--
-- Name: documents_id_seq; Type: SEQUENCE; Schema: public; Owner: efdi_user
--

CREATE SEQUENCE public.documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.documents_id_seq OWNER TO efdi_user;

--
-- Name: documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: efdi_user
--

ALTER SEQUENCE public.documents_id_seq OWNED BY public.documents.id;


--
-- Name: extraction_results; Type: TABLE; Schema: public; Owner: efdi_user
--

CREATE TABLE public.extraction_results (
    id integer NOT NULL,
    document_id integer NOT NULL,
    document_type character varying(30) NOT NULL,
    engine_name character varying(30) NOT NULL,
    fields jsonb NOT NULL,
    overall_confidence double precision NOT NULL,
    fields_found_count integer NOT NULL,
    fields_total_count integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.extraction_results OWNER TO efdi_user;

--
-- Name: extraction_results_id_seq; Type: SEQUENCE; Schema: public; Owner: efdi_user
--

CREATE SEQUENCE public.extraction_results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.extraction_results_id_seq OWNER TO efdi_user;

--
-- Name: extraction_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: efdi_user
--

ALTER SEQUENCE public.extraction_results_id_seq OWNED BY public.extraction_results.id;


--
-- Name: ocr_results; Type: TABLE; Schema: public; Owner: efdi_user
--

CREATE TABLE public.ocr_results (
    id integer NOT NULL,
    document_id integer NOT NULL,
    engine_name character varying(30) NOT NULL,
    page_count integer NOT NULL,
    full_text text NOT NULL,
    average_confidence double precision NOT NULL,
    raw_blocks jsonb NOT NULL,
    processing_time_ms integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.ocr_results OWNER TO efdi_user;

--
-- Name: ocr_results_id_seq; Type: SEQUENCE; Schema: public; Owner: efdi_user
--

CREATE SEQUENCE public.ocr_results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ocr_results_id_seq OWNER TO efdi_user;

--
-- Name: ocr_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: efdi_user
--

ALTER SEQUENCE public.ocr_results_id_seq OWNED BY public.ocr_results.id;


--
-- Name: training_examples; Type: TABLE; Schema: public; Owner: efdi_user
--

CREATE TABLE public.training_examples (
    id integer NOT NULL,
    document_id integer NOT NULL,
    corrected_by integer NOT NULL,
    task_type character varying(20) NOT NULL,
    document_type character varying(30) NOT NULL,
    source_text text NOT NULL,
    field_key character varying(50),
    predicted_value text,
    corrected_value text NOT NULL,
    extra_context jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.training_examples OWNER TO efdi_user;

--
-- Name: training_examples_id_seq; Type: SEQUENCE; Schema: public; Owner: efdi_user
--

CREATE SEQUENCE public.training_examples_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.training_examples_id_seq OWNER TO efdi_user;

--
-- Name: training_examples_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: efdi_user
--

ALTER SEQUENCE public.training_examples_id_seq OWNED BY public.training_examples.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: efdi_user
--

CREATE TABLE public.users (
    id integer NOT NULL,
    username character varying(50) NOT NULL,
    password_hash character varying(255) NOT NULL,
    role character varying(30) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    email character varying(120) NOT NULL,
    full_name character varying(120) NOT NULL,
    is_active boolean NOT NULL
);


ALTER TABLE public.users OWNER TO efdi_user;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: efdi_user
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO efdi_user;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: efdi_user
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: validation_results; Type: TABLE; Schema: public; Owner: efdi_user
--

CREATE TABLE public.validation_results (
    id integer NOT NULL,
    document_id integer NOT NULL,
    document_type character varying(30) NOT NULL,
    engine_name character varying(50) NOT NULL,
    is_valid boolean NOT NULL,
    error_count integer NOT NULL,
    warning_count integer NOT NULL,
    issues jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.validation_results OWNER TO efdi_user;

--
-- Name: validation_results_id_seq; Type: SEQUENCE; Schema: public; Owner: efdi_user
--

CREATE SEQUENCE public.validation_results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.validation_results_id_seq OWNER TO efdi_user;

--
-- Name: validation_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: efdi_user
--

ALTER SEQUENCE public.validation_results_id_seq OWNED BY public.validation_results.id;


--
-- Name: workflow_history; Type: TABLE; Schema: public; Owner: efdi_user
--

CREATE TABLE public.workflow_history (
    id integer NOT NULL,
    document_id integer NOT NULL,
    action character varying(30) NOT NULL,
    from_status character varying(30) NOT NULL,
    to_status character varying(30) NOT NULL,
    comment text,
    performed_by integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.workflow_history OWNER TO efdi_user;

--
-- Name: workflow_history_id_seq; Type: SEQUENCE; Schema: public; Owner: efdi_user
--

CREATE SEQUENCE public.workflow_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workflow_history_id_seq OWNER TO efdi_user;

--
-- Name: workflow_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: efdi_user
--

ALTER SEQUENCE public.workflow_history_id_seq OWNED BY public.workflow_history.id;


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: classification_results id; Type: DEFAULT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.classification_results ALTER COLUMN id SET DEFAULT nextval('public.classification_results_id_seq'::regclass);


--
-- Name: documents id; Type: DEFAULT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.documents ALTER COLUMN id SET DEFAULT nextval('public.documents_id_seq'::regclass);


--
-- Name: extraction_results id; Type: DEFAULT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.extraction_results ALTER COLUMN id SET DEFAULT nextval('public.extraction_results_id_seq'::regclass);


--
-- Name: ocr_results id; Type: DEFAULT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.ocr_results ALTER COLUMN id SET DEFAULT nextval('public.ocr_results_id_seq'::regclass);


--
-- Name: training_examples id; Type: DEFAULT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.training_examples ALTER COLUMN id SET DEFAULT nextval('public.training_examples_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: validation_results id; Type: DEFAULT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.validation_results ALTER COLUMN id SET DEFAULT nextval('public.validation_results_id_seq'::regclass);


--
-- Name: workflow_history id; Type: DEFAULT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.workflow_history ALTER COLUMN id SET DEFAULT nextval('public.workflow_history_id_seq'::regclass);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: classification_results classification_results_pkey; Type: CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.classification_results
    ADD CONSTRAINT classification_results_pkey PRIMARY KEY (id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: documents documents_stored_filename_key; Type: CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_stored_filename_key UNIQUE (stored_filename);


--
-- Name: extraction_results extraction_results_pkey; Type: CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.extraction_results
    ADD CONSTRAINT extraction_results_pkey PRIMARY KEY (id);


--
-- Name: ocr_results ocr_results_pkey; Type: CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.ocr_results
    ADD CONSTRAINT ocr_results_pkey PRIMARY KEY (id);


--
-- Name: training_examples training_examples_pkey; Type: CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.training_examples
    ADD CONSTRAINT training_examples_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: validation_results validation_results_pkey; Type: CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.validation_results
    ADD CONSTRAINT validation_results_pkey PRIMARY KEY (id);


--
-- Name: workflow_history workflow_history_pkey; Type: CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.workflow_history
    ADD CONSTRAINT workflow_history_pkey PRIMARY KEY (id);


--
-- Name: ix_audit_logs_action; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_audit_logs_action ON public.audit_logs USING btree (action);


--
-- Name: ix_audit_logs_document_id; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_audit_logs_document_id ON public.audit_logs USING btree (document_id);


--
-- Name: ix_audit_logs_user_id; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_audit_logs_user_id ON public.audit_logs USING btree (user_id);


--
-- Name: ix_classification_results_document_id; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_classification_results_document_id ON public.classification_results USING btree (document_id);


--
-- Name: ix_documents_document_type; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_documents_document_type ON public.documents USING btree (document_type);


--
-- Name: ix_documents_file_hash; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_documents_file_hash ON public.documents USING btree (file_hash);


--
-- Name: ix_documents_status; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_documents_status ON public.documents USING btree (status);


--
-- Name: ix_documents_uploaded_by; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_documents_uploaded_by ON public.documents USING btree (uploaded_by);


--
-- Name: ix_extraction_results_document_id; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_extraction_results_document_id ON public.extraction_results USING btree (document_id);


--
-- Name: ix_ocr_results_document_id; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_ocr_results_document_id ON public.ocr_results USING btree (document_id);


--
-- Name: ix_training_examples_document_id; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_training_examples_document_id ON public.training_examples USING btree (document_id);


--
-- Name: ix_training_examples_task_type; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_training_examples_task_type ON public.training_examples USING btree (task_type);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_username; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE UNIQUE INDEX ix_users_username ON public.users USING btree (username);


--
-- Name: ix_validation_results_document_id; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_validation_results_document_id ON public.validation_results USING btree (document_id);


--
-- Name: ix_workflow_history_document_id; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_workflow_history_document_id ON public.workflow_history USING btree (document_id);


--
-- Name: ix_workflow_history_performed_by; Type: INDEX; Schema: public; Owner: efdi_user
--

CREATE INDEX ix_workflow_history_performed_by ON public.workflow_history USING btree (performed_by);


--
-- Name: audit_logs audit_logs_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);


--
-- Name: audit_logs audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: classification_results classification_results_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.classification_results
    ADD CONSTRAINT classification_results_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);


--
-- Name: documents documents_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id);


--
-- Name: extraction_results extraction_results_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.extraction_results
    ADD CONSTRAINT extraction_results_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);


--
-- Name: ocr_results ocr_results_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.ocr_results
    ADD CONSTRAINT ocr_results_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);


--
-- Name: training_examples training_examples_corrected_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.training_examples
    ADD CONSTRAINT training_examples_corrected_by_fkey FOREIGN KEY (corrected_by) REFERENCES public.users(id);


--
-- Name: training_examples training_examples_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.training_examples
    ADD CONSTRAINT training_examples_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);


--
-- Name: validation_results validation_results_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.validation_results
    ADD CONSTRAINT validation_results_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);


--
-- Name: workflow_history workflow_history_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.workflow_history
    ADD CONSTRAINT workflow_history_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);


--
-- Name: workflow_history workflow_history_performed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: efdi_user
--

ALTER TABLE ONLY public.workflow_history
    ADD CONSTRAINT workflow_history_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.users(id);


--
-- PostgreSQL database dump complete
--

\unrestrict Nvv7b8I3hAREHddo3NqRzNbtiDgRhP9JppeZBOXsPMgNNPkdlIDplT1DCdmPBMa

