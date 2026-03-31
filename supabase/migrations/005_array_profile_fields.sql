-- Migration 005: Add array profile fields for work experience, education, and skills
-- These support the hybrid LLM fill approach which sends full structured profile data.

-- Add work_experience JSONB array
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'user_profiles'
      AND column_name = 'work_experience'
  ) THEN
    ALTER TABLE public.user_profiles
      ADD COLUMN work_experience JSONB DEFAULT '[]';
  END IF;
END $$;

-- Add education JSONB array
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'user_profiles'
      AND column_name = 'education'
  ) THEN
    ALTER TABLE public.user_profiles
      ADD COLUMN education JSONB DEFAULT '[]';
  END IF;
END $$;

-- Add skills TEXT array
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'user_profiles'
      AND column_name = 'skills'
  ) THEN
    ALTER TABLE public.user_profiles
      ADD COLUMN skills TEXT[] DEFAULT '{}';
  END IF;
END $$;

-- Add comments
COMMENT ON COLUMN public.user_profiles.work_experience IS 'Array of work experiences [{title, company, location, start, end, current, achievements[]}]';
COMMENT ON COLUMN public.user_profiles.education IS 'Array of education entries [{school, degree, field, location, start, end, gpa}]';
COMMENT ON COLUMN public.user_profiles.skills IS 'Flat array of skill strings for form filling and matching';
